import sys
import os
import csv
import numpy as np
from PyQt5.QtCore import (
    Qt,
    QTimer,
    QThread,
    QObject,
    pyqtSignal,
    pyqtSlot,
    QRectF,
)
from PyQt5.QtGui import (
    QPixmap,
    QImage,
    QPainter,
    QFont,
    QFontMetrics,
    QPainterPath,
    QPen,
)
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QSpinBox,
    QSlider,
    QProgressBar,
    QCheckBox,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsItem,
)
from tifffile import TiffFile, imwrite
from PIL import Image

from utils.roi import normalized_roi_to_bounds
from utils.tiff_crop import CropCanceled, export_cropped_tiff


class OverlayItem(QGraphicsItem):
    """Simple item for drawing overlay text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.force_text = ""
        self.frame_text = ""
        self.font = QFont("Arial", 10)

    def set_text(self, force_text, frame_text=None):
        self.force_text = force_text
        self.frame_text = frame_text or ""
        self.update()

    def set_font(self, font):
        self.font = font
        self.update()

    def boundingRect(self):
        if self.parentItem():
            rect = self.parentItem().boundingRect()
            return QRectF(0, 0, rect.width(), rect.height())
        return QRectF()

    def paint(self, painter, option, widget=None):
        if not self.force_text and not self.frame_text:
            return
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        painter.setFont(self.font)
        metrics = QFontMetrics(self.font)
        rect = self.boundingRect()

        if self.force_text:
            x = 10
            y = rect.height() - metrics.descent() - 10
            path = QPainterPath()
            path.addText(x, y, self.font, self.force_text)
            painter.setPen(QPen(Qt.black, 2))
            painter.drawPath(path)
            painter.fillPath(path, Qt.white)

        if self.frame_text:
            fx = 10
            fy = metrics.ascent() + 10
            fpath = QPainterPath()
            fpath.addText(fx, fy, self.font, self.frame_text)
            painter.drawPath(fpath)
            painter.fillPath(fpath, Qt.white)


class PlaybackLoader(QObject):
    """Load TIFF/CSV data and emit frames as they are read."""

    progress = pyqtSignal(int, int)
    frame_loaded = pyqtSignal(int, np.ndarray, float, int)
    finished = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, tiff_path, csv_path, parent=None):
        super().__init__(parent)
        self.tiff_path = tiff_path
        self.csv_path = csv_path

    @pyqtSlot()
    def run(self):
        try:
            with open(self.csv_path, "r", newline="") as f:
                reader = csv.DictReader(f)
                forces = []
                for row in reader:
                    raw = row.get("force")
                    if raw in (None, ""):
                        raw = row.get("pressure", 0)
                    try:
                        forces.append(float(raw))
                    except (TypeError, ValueError):
                        forces.append(0.0)
        except Exception as e:
            self.error.emit(str(e))
            forces = []

        total = 0
        try:
            with TiffFile(self.tiff_path) as tif:
                total = len(tif.pages)
                for idx, page in enumerate(tif.pages):
                    frame = page.asarray()
                    force = forces[idx] if idx < len(forces) else 0
                    self.frame_loaded.emit(idx, frame, force, total)
                    self.progress.emit(idx + 1, total)
        except Exception as e:
            self.error.emit(str(e))

        self.finished.emit(total)


class RoiStackExporter(QObject):
    """Stream a source TIFF through a fixed crop into a new TIFF stack."""

    progress = pyqtSignal(int, int)
    finished = pyqtSignal(str, int)
    canceled = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, source_path, output_path, bounds, source_shape, parent=None):
        super().__init__(parent)
        self.source_path = source_path
        self.output_path = output_path
        self.bounds = bounds
        self.source_shape = tuple(source_shape[:2])
        self._abort = False

    def stop(self):
        self._abort = True

    @pyqtSlot()
    def run(self):
        try:
            frame_count = export_cropped_tiff(
                self.source_path,
                self.output_path,
                self.bounds,
                self.source_shape,
                should_cancel=lambda: self._abort,
                on_progress=self.progress.emit,
            )
            self.finished.emit(self.output_path, frame_count)
        except CropCanceled:
            self.canceled.emit()
        except Exception as exc:
            self.error.emit(str(exc))


class GraphicsImageView(QGraphicsView):
    """Interactive view for displaying and selecting ROIs."""

    roi_changed = pyqtSignal(QRectF)
    roi_finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.pixmap_item = QGraphicsPixmapItem()
        self.scene().addItem(self.pixmap_item)
        self.overlay_item = OverlayItem(self.pixmap_item)
        self.overlay_item.setZValue(1)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._drawing_roi = False
        self._roi_item = None
        self._start_pos = None
        self._normalized_roi = None

    def set_pixmap(self, pixmap: QPixmap):
        self.pixmap_item.setPixmap(pixmap)
        self.setSceneRect(QRectF(pixmap.rect()))
        if self._roi_item is not None and self._normalized_roi is not None:
            left, top, right, bottom = self._normalized_roi
            self._roi_item.setRect(
                QRectF(
                    left * pixmap.width(),
                    top * pixmap.height(),
                    (right - left) * pixmap.width(),
                    (bottom - top) * pixmap.height(),
                )
            )
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def update_overlay(self, force, frame_text, font_size, visible=True):
        font = QFont("Arial", max(1, font_size))
        self.overlay_item.set_font(font)
        self.overlay_item.set_text(f"{force:.2f} mN", frame_text)
        self.overlay_item.setVisible(visible)

    def wheelEvent(self, event):
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)
        event.accept()

    # ─── ROI Handling ────────────────────────────────────────────────────
    def enable_roi(self, enabled: bool):
        self._drawing_roi = enabled
        if enabled:
            self.setDragMode(QGraphicsView.NoDrag)
            self.viewport().setCursor(Qt.CrossCursor)
        else:
            self._start_pos = None
            self.viewport().unsetCursor()
            self.setDragMode(QGraphicsView.ScrollHandDrag)

    def clear_roi(self):
        if self._roi_item is not None:
            self.scene().removeItem(self._roi_item)
            self._roi_item = None
        self._normalized_roi = None
        self.roi_changed.emit(QRectF())

    def get_roi_rect(self):
        return self._roi_item.rect() if self._normalized_roi is not None else None

    def get_normalized_roi(self):
        return self._normalized_roi

    def _update_roi(self, current_pos):
        rect = QRectF(self._start_pos, current_pos).normalized()
        image_rect = self.pixmap_item.boundingRect()
        rect = rect.intersected(image_rect)
        if rect.isEmpty() or image_rect.isEmpty():
            self._roi_item.setRect(QRectF())
            self._normalized_roi = None
        else:
            self._roi_item.setRect(rect)
            self._normalized_roi = (
                rect.left() / image_rect.width(),
                rect.top() / image_rect.height(),
                rect.right() / image_rect.width(),
                rect.bottom() / image_rect.height(),
            )
        self.roi_changed.emit(rect)

    def mousePressEvent(self, event):
        if self._drawing_roi and event.button() == Qt.LeftButton:
            self.clear_roi()
            self._start_pos = self.mapToScene(event.pos())
            self._roi_item = QGraphicsRectItem()
            pen = QPen(Qt.red)
            pen.setWidth(2)
            pen.setCosmetic(True)
            self._roi_item.setPen(pen)
            self._roi_item.setZValue(2)
            self.scene().addItem(self._roi_item)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drawing_roi and self._start_pos is not None:
            cur = self.mapToScene(event.pos())
            self._update_roi(cur)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if (
            self._drawing_roi
            and event.button() == Qt.LeftButton
            and self._start_pos is not None
        ):
            cur = self.mapToScene(event.pos())
            self._update_roi(cur)
            self._start_pos = None
            if self._normalized_roi is not None:
                self.roi_finished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class FrameRenderer(QObject):
    """Render frames in a background thread, optionally drawing overlay."""

    progress = pyqtSignal(int, int)
    finished = pyqtSignal(list)

    def __init__(self, frames, forces, label_size, font_value, draw_overlay=True, parent=None):
        super().__init__(parent)
        self.frames = frames
        self.forces = forces
        self.label_w, self.label_h = label_size
        self.font_value = font_value
        self.draw_overlay = draw_overlay
        self._abort = False
        self.total_frames = len(frames)

    def stop(self):
        self._abort = True

    @pyqtSlot()
    def run(self):
        images = []
        total = len(self.frames)
        for idx, frame in enumerate(self.frames):
            if self._abort:
                return
            force = self.forces[min(idx, len(self.forces) - 1)]
            img = self.render_image(idx, frame, force)
            images.append(img)
            self.progress.emit(idx + 1, total)
        if not self._abort:
            self.finished.emit(images)

    def render_image(self, idx, frame, force):
        frame_h, frame_w = frame.shape
        scale = min(self.label_w / frame_w, self.label_h / frame_h)
        disp_w = max(1, int(frame_w * scale))
        disp_h = max(1, int(frame_h * scale))

        qimg = QImage(
            frame.data, frame_w, frame_h, frame.strides[0], QImage.Format_Grayscale8
        )
        qimg = qimg.scaled(disp_w, disp_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        qimg = qimg.convertToFormat(QImage.Format_Grayscale8)

        painter = QPainter(qimg)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

        if self.draw_overlay:
            scale_factor = disp_h / 500
            font_size = int(self.font_value * scale_factor)
            font = QFont("Arial", font_size)
            painter.setFont(font)

            text = f"{force:.2f} mN"
            metrics = QFontMetrics(font)
            x = 10
            y = disp_h - metrics.descent() - 10

            path = QPainterPath()
            path.addText(x, y, font, text)
            painter.setPen(QPen(Qt.black, 2))
            painter.drawPath(path)
            painter.fillPath(path, Qt.white)

            # frame count in top-left corner
            frame_text = f"{idx + 1}/{self.total_frames}"
            f_metrics = QFontMetrics(font)
            fx = 10
            fy = f_metrics.ascent() + 10
            frame_path = QPainterPath()
            frame_path.addText(fx, fy, font, frame_text)
            painter.drawPath(frame_path)
            painter.fillPath(frame_path, Qt.white)
        painter.end()

        return qimg.copy()


class PlaybackWindow(QMainWindow):
    """Display a TIFF stack with optional force overlay and playback controls."""

    def __init__(self, tiff_path=None, csv_path=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Playback")
        self.resize(800, 600)

        self.frames = []
        self.forces = []
        self.pre_rendered_frames = []
        self.loader_thread = None
        self.loader = None
        self.render_thread = None
        self.renderer = None
        self.crop_thread = None
        self.crop_worker = None
        self.tiff_path = None
        self.csv_path = None
        self._crop_active = False
        self.current_frame = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame)

        # ─── Widgets ──────────────────────────────────────────────────────
        self.view = GraphicsImageView()
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self.crop_progress = QProgressBar()
        self.crop_progress.setFormat("Cropping frame %v of %m")
        self.crop_progress.setVisible(False)
        self.play_btn = QPushButton("\u25b6 Play")
        self.play_btn.setCheckable(True)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.frame_label = QLabel("0/0")

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 1000)
        self.fps_spin.setValue(10)
        self.fps_spin.valueChanged.connect(self.update_fps)

        self.font_spin = QSpinBox()
        self.font_spin.setRange(10, 200)
        self.font_spin.setValue(10)
        self.font_spin.valueChanged.connect(self._update_overlay)

        self.overlay_cb = QCheckBox("Show Overlay")
        self.overlay_cb.setChecked(True)
        self.overlay_cb.toggled.connect(self._update_overlay)

        self.roi_btn = QPushButton("Draw ROI")
        self.roi_btn.setObjectName("roiDrawButton")
        self.roi_btn.setCheckable(True)
        self.roi_btn.setToolTip("Select, then drag over the image to define a crop")
        self.zoom_roi_btn = QPushButton("Zoom ROI")
        self.export_roi_btn = QPushButton("Export ROI PNG")
        self.export_roi_stack_btn = QPushButton("Export Cropped TIFF")
        self.export_roi_stack_btn.setToolTip(
            "Crop this ROI from every frame into a new TIFF stack"
        )

        self.export_btn = QPushButton("💾 Export Overlay TIFF")
        self.snapshot_btn = QPushButton("🖼 Export Frame PNG")

        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(4, 4, 4, 4)
        controls_layout.setSpacing(6)
        controls_layout.addWidget(self.play_btn)
        controls_layout.addWidget(self.slider, stretch=1)
        controls_layout.addWidget(self.frame_label)

        options_layout = QHBoxLayout()
        options_layout.setContentsMargins(4, 0, 4, 4)
        options_layout.setSpacing(6)
        options_layout.addWidget(QLabel("FPS:"))
        options_layout.addWidget(self.fps_spin)
        options_layout.addWidget(QLabel("Font:"))
        options_layout.addWidget(self.font_spin)
        options_layout.addWidget(self.overlay_cb)
        options_layout.addStretch(1)
        options_layout.addWidget(self.snapshot_btn)
        options_layout.addWidget(self.export_btn)

        roi_layout = QHBoxLayout()
        roi_layout.setContentsMargins(4, 0, 4, 4)
        roi_layout.setSpacing(6)
        roi_layout.addWidget(QLabel("ROI:"))
        roi_layout.addWidget(self.roi_btn)
        roi_layout.addWidget(self.zoom_roi_btn)
        roi_layout.addStretch(1)
        roi_layout.addWidget(self.export_roi_btn)
        roi_layout.addWidget(self.export_roi_stack_btn)

        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        layout.addWidget(self.view, stretch=1)
        layout.addWidget(self.progress)
        layout.addWidget(self.crop_progress)
        layout.addLayout(controls_layout)
        layout.addLayout(options_layout)
        layout.addLayout(roi_layout)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # ─── Signals ──────────────────────────────────────────────────────
        self.play_btn.clicked.connect(self._toggle_play)
        self.slider.valueChanged.connect(self.set_frame)
        self.export_btn.clicked.connect(self.export_overlay)
        self.snapshot_btn.clicked.connect(self.export_snapshot)
        self.roi_btn.toggled.connect(self.toggle_roi_mode)
        self.zoom_roi_btn.clicked.connect(self.zoom_to_roi)
        self.export_roi_btn.clicked.connect(self.export_roi)
        self.export_roi_stack_btn.clicked.connect(self.export_roi_stack)
        self.view.roi_changed.connect(self._on_roi_changed)
        self.view.roi_finished.connect(self._finish_roi_drawing)

        self.zoom_roi_btn.setEnabled(False)
        self.export_roi_btn.setEnabled(False)
        self.export_roi_stack_btn.setEnabled(False)

        if tiff_path and csv_path:
            self.load_files(tiff_path, csv_path)
        else:
            self.pick_files()

    # ─── File Loading ─────────────────────────────────────────────────────
    def pick_files(self):
        tiff, _ = QFileDialog.getOpenFileName(
            self, "Select TIFF", "", "TIFF files (*.tif *.tiff)"
        )
        if not tiff:
            return
        csv_path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV", "", "CSV files (*.csv)"
        )
        if not csv_path:
            return
        self.load_files(tiff, csv_path)

    def load_files(self, tiff_path, csv_path):
        # Show progress bar and start worker thread to avoid blocking UI
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.statusBar().showMessage("Loading files...")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        self.frames.clear()
        self.pre_rendered_frames.clear()
        self.forces.clear()
        self.view.clear_roi()
        self.tiff_path = os.path.abspath(tiff_path)
        self.csv_path = os.path.abspath(csv_path)

        self.loader_thread = QThread(self)
        self.loader = PlaybackLoader(tiff_path, csv_path)
        self.loader.moveToThread(self.loader_thread)
        self.loader_thread.started.connect(self.loader.run)
        self.loader.progress.connect(self._update_progress)
        self.loader.frame_loaded.connect(self._on_frame_loaded)
        self.loader.finished.connect(self._loading_finished)
        self.loader.error.connect(self._show_error)
        self.loader.finished.connect(self.loader_thread.quit)
        self.loader_thread.finished.connect(self.loader.deleteLater)
        self.loader_thread.finished.connect(self.loader_thread.deleteLater)
        self.loader_thread.start()

    def _update_progress(self, current, total):
        self.progress.setMaximum(total)
        self.progress.setValue(current)

    def _on_frame_loaded(self, idx, frame, force, total_frames):
        self.frames.append(frame)
        self.forces.append(force)
        pix = self.render_pixmap(frame, force, idx, total_frames)
        self.pre_rendered_frames.append(pix)
        if idx == 0:
            self.current_frame = 0
            self.slider.setEnabled(True)
            self.play_btn.setEnabled(True)
            self._refresh_roi_controls()
        if self.slider.maximum() != len(self.frames) - 1:
            self.slider.setRange(0, max(0, len(self.frames) - 1))
        if idx == 0:
            self.show_frame()

    def _loading_finished(self, _total_frames):
        QApplication.restoreOverrideCursor()
        self.statusBar().clearMessage()
        self.progress.setVisible(False)
        if self.pre_rendered_frames:
            self.show_frame()
        self.slider.setEnabled(bool(self.frames))
        self.play_btn.setEnabled(bool(self.frames))
        self._refresh_roi_controls()

    def _show_error(self, msg):
        self.statusBar().showMessage(msg, 5000)

    # ─── Overlay Helpers ─────────────────────────────────────────────────-
    def overlay_frame(
        self,
        frame,
        force,
        base_font_size,
        frame_idx=None,
        total_frames=None,
        preview_size=(500, 500),
    ):
        """Return ``frame`` with force text and frame count drawn.

        ``base_font_size`` represents the font size used when the preview label
        size is ``preview_size`` (defaults to ``(500, 500)``). The font will be
        scaled relative to the export frame size so the overlay appears
        consistent between the on-screen preview and exported image.
        """
        h, w = frame.shape
        qimg = QImage(
            frame.data, w, h, frame.strides[0], QImage.Format_Grayscale8
        ).copy()
        painter = QPainter(qimg)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)

        preview_w, preview_h = preview_size
        scale = min(preview_w / max(1, w), preview_h / max(1, h))
        disp_h = h * scale
        scale_factor = disp_h / 500
        target_font_size = int(max(1, base_font_size * scale_factor))
        font = QFont("Arial", target_font_size)
        painter.setFont(font)

        text = f"{force:.2f} mN"
        metrics = QFontMetrics(font)
        x = 20
        y = h - metrics.descent() - 20

        path = QPainterPath()
        path.addText(x, y, font, text)
        painter.setPen(QPen(Qt.black, 2))
        painter.drawPath(path)
        painter.fillPath(path, Qt.white)

        if frame_idx is not None and total_frames is not None:
            frame_text = f"{frame_idx + 1}/{total_frames}"
            fx = 20
            fy = metrics.ascent() + 20
            fpath = QPainterPath()
            fpath.addText(fx, fy, font, frame_text)
            painter.drawPath(fpath)
            painter.fillPath(fpath, Qt.white)
        painter.end()

        ptr = qimg.bits()
        ptr.setsize(qimg.byteCount())
        arr = np.frombuffer(ptr, np.uint8).reshape((h, w))
        return arr.copy()

    def render_pixmap(self, frame, force, frame_idx=None, total_frames=None):
        """Return a scaled :class:`QPixmap` of ``frame``."""
        label_w, label_h = max(1, self.view.viewport().width()), max(1, self.view.viewport().height())
        frame_h, frame_w = frame.shape
        scale = min(label_w / frame_w, label_h / frame_h)
        disp_w = max(1, int(frame_w * scale))
        disp_h = max(1, int(frame_h * scale))

        qimg = QImage(
            frame.data, frame_w, frame_h, frame.strides[0], QImage.Format_Grayscale8
        )
        qimg = qimg.scaled(disp_w, disp_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        qimg = qimg.convertToFormat(QImage.Format_Grayscale8)

        return QPixmap.fromImage(qimg)

    def pre_render_frames_async(self):
        """Asynchronously pre-render frames for smooth playback."""
        if not self.frames:
            return

        # If a previous rendering thread exists, ensure it has fully
        # stopped before starting another. ``render_thread`` may already
        # have been deleted via ``deleteLater`` so guard against calling
        # methods on a dead QObject.
        if self.render_thread:
            try:
                if self.render_thread.isRunning():
                    self.renderer.stop()
                    self.render_thread.quit()
                    self.render_thread.wait()
            except RuntimeError:
                # The underlying C++ object was destroyed; reset refs.
                self.render_thread = None
                self.renderer = None

        self.progress.setVisible(True)
        self.progress.setValue(0)

        label_size = (
            max(1, self.view.viewport().width()),
            max(1, self.view.viewport().height()),
        )
        font_value = self.font_spin.value()

        self.render_thread = QThread(self)
        self.renderer = FrameRenderer(
            self.frames,
            self.forces or [0] * len(self.frames),
            label_size,
            font_value,
            False,
        )
        self.renderer.moveToThread(self.render_thread)
        self.render_thread.started.connect(self.renderer.run)
        self.renderer.progress.connect(self._update_progress)
        self.renderer.finished.connect(self._rendering_finished)
        self.renderer.finished.connect(self.render_thread.quit)
        self.render_thread.finished.connect(self.renderer.deleteLater)
        self.render_thread.finished.connect(self.render_thread.deleteLater)
        self.render_thread.start()

    def regenerate_frames(self):
        """Re-render frames and update the current display."""
        self.pre_render_frames_async()

    def _rendering_finished(self, images):
        self.pre_rendered_frames = [QPixmap.fromImage(img) for img in images]
        self.progress.setVisible(False)
        self.slider.setEnabled(True)
        self.play_btn.setEnabled(True)
        # Rendering thread is finished; clear references so future checks
        # don't try to access a deleted QObject.
        self.render_thread = None
        self.renderer = None
        self.show_frame()

    def show_frame(self):
        if not self.pre_rendered_frames:
            return
        pixmap = self.pre_rendered_frames[self.current_frame]
        self.view.set_pixmap(pixmap)
        if self.slider.maximum() != len(self.frames) - 1:
            self.slider.setRange(0, max(0, len(self.frames) - 1))
        self.slider.blockSignals(True)
        self.slider.setValue(self.current_frame)
        self.slider.blockSignals(False)
        self.frame_label.setText(f"{self.current_frame + 1}/{len(self.frames)}")
        force = self.forces[min(self.current_frame, len(self.forces) - 1)]
        scale_factor = pixmap.height() / 500
        font_size = int(self.font_spin.value() * scale_factor)
        frame_text = f"{self.current_frame + 1}/{len(self.frames)}" if self.overlay_cb.isChecked() else ""
        self.view.update_overlay(
            force,
            frame_text,
            font_size,
            self.overlay_cb.isChecked(),
        )

    def _update_overlay(self):
        if self.pre_rendered_frames:
            self.show_frame()

    # ─── Controls ─────────────────────────────────────────────────────────
    def _toggle_play(self, checked):
        if checked:
            self.play_btn.setText("\u23f8 Pause")
            self.timer.start(int(1000 / self.fps_spin.value()))
        else:
            self.play_btn.setText("\u25b6 Play")
            self.timer.stop()

    def next_frame(self):
        if not self.frames:
            return
        self.current_frame = (self.current_frame + 1) % len(self.frames)
        self.show_frame()

    def set_frame(self, idx):
        if not self.frames:
            return
        self.current_frame = max(0, min(idx, len(self.frames) - 1))
        self.show_frame()

    def update_fps(self):
        if self.timer.isActive():
            self.timer.setInterval(int(1000 / self.fps_spin.value()))

    def export_overlay(self):
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Overlay TIFF", "", "TIFF files (*.tif *.tiff)"
        )
        if not out_path:
            return
        self.statusBar().showMessage("Exporting overlay...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        base_font = self.font_spin.value()
        preview_size = (
            max(1, self.view.viewport().width()),
            max(1, self.view.viewport().height()),
        )
        total = len(self.frames)
        overlaid_frames = [
            self.overlay_frame(
                f,
                p,
                base_font,
                idx,
                total,
                preview_size=preview_size,
            )
            for idx, (f, p) in enumerate(zip(self.frames, self.forces))
        ]
        imwrite(out_path, np.array(overlaid_frames), photometric="minisblack")
        QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(f"Saved: {os.path.basename(out_path)}", 3000)

    def export_snapshot(self):
        if not self.frames:
            return
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Frame PNG",
            "",
            "PNG files (*.png);;TIFF files (*.tif *.tiff)",
        )
        if not out_path:
            return
        frame = self.frames[self.current_frame]
        force = self.forces[min(self.current_frame, len(self.forces) - 1)]
        base_font = self.font_spin.value()
        preview_size = (
            max(1, self.view.viewport().width()),
            max(1, self.view.viewport().height()),
        )
        overlaid = self.overlay_frame(
            frame,
            force,
            base_font,
            self.current_frame,
            len(self.frames),
            preview_size=preview_size,
        )
        Image.fromarray(overlaid).save(out_path)
        self.statusBar().showMessage(
            f"Snapshot saved: {os.path.basename(out_path)}",
            3000,
        )

    # ─── ROI Helpers ─────────────────────────────────────────────────────
    def toggle_roi_mode(self, checked: bool):
        self.view.enable_roi(checked)
        self.roi_btn.setText("Cancel ROI" if checked else "Draw ROI")
        if checked:
            self.statusBar().showMessage(
                "ROI mode active — drag over the image to select the crop area"
            )
        else:
            bounds = self._roi_frame_bounds()
            if bounds is None:
                self.statusBar().showMessage("ROI drawing canceled", 1500)
            else:
                x0, y0, x1, y1 = bounds
                self.statusBar().showMessage(
                    f"ROI selected: {x1 - x0}×{y1 - y0} px at ({x0}, {y0})"
                )

    def _finish_roi_drawing(self):
        bounds = self._roi_frame_bounds()
        self.roi_btn.setChecked(False)
        if bounds is not None:
            x0, y0, x1, y1 = bounds
            self.statusBar().showMessage(
                f"ROI selected: {x1 - x0}×{y1 - y0} px at ({x0}, {y0})"
            )

    def _roi_frame_bounds(self):
        if not self.frames:
            return None
        return normalized_roi_to_bounds(
            self.view.get_normalized_roi(),
            self.frames[self.current_frame].shape,
        )

    def _crop_is_running(self):
        if self._crop_active:
            return True
        if self.crop_thread is None:
            return False
        try:
            return self.crop_thread.isRunning()
        except RuntimeError:
            return False

    def _refresh_roi_controls(self):
        has_roi = self._roi_frame_bounds() is not None
        busy = self._crop_is_running()
        self.roi_btn.setEnabled(bool(self.frames) and not busy)
        self.zoom_roi_btn.setEnabled(has_roi and not busy)
        self.export_roi_btn.setEnabled(has_roi and not busy)
        self.export_roi_stack_btn.setEnabled(has_roi and not busy)

    def _on_roi_changed(self, _rect):
        self._refresh_roi_controls()
        bounds = self._roi_frame_bounds()
        if bounds is not None:
            x0, y0, x1, y1 = bounds
            self.statusBar().showMessage(
                f"ROI: {x1 - x0}\u00d7{y1 - y0} px at ({x0}, {y0})"
            )

    def zoom_to_roi(self):
        rect = self.view.get_roi_rect()
        if rect:
            self.view.fitInView(rect, Qt.KeepAspectRatio)

    def export_roi(self):
        bounds = self._roi_frame_bounds()
        if bounds is None:
            self.statusBar().showMessage("Draw ROI first", 2000)
            return
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save ROI PNG",
            "",
            "PNG files (*.png);;TIFF files (*.tif *.tiff)",
        )
        if not out_path:
            return
        frame = self.frames[self.current_frame]
        x0, y0, x1, y1 = bounds
        roi_frame = frame[y0:y1, x0:x1]
        force = self.forces[min(self.current_frame, len(self.forces) - 1)]
        base_font = self.font_spin.value()
        preview_size = (
            max(1, self.view.viewport().width()),
            max(1, self.view.viewport().height()),
        )
        overlaid = self.overlay_frame(
            roi_frame,
            force,
            base_font,
            self.current_frame,
            len(self.frames),
            preview_size=preview_size,
        )
        Image.fromarray(overlaid).save(out_path)
        self.statusBar().showMessage(
            f"ROI saved: {os.path.basename(out_path)}",
            3000,
        )

    def export_roi_stack(self):
        bounds = self._roi_frame_bounds()
        if bounds is None or not self.tiff_path:
            self.statusBar().showMessage("Draw ROI first", 2000)
            return
        if self._crop_is_running():
            return

        source_stem, _ = os.path.splitext(self.tiff_path)
        suggested_path = f"{source_stem}_cropped.tif"
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Cropped TIFF Stack",
            suggested_path,
            "TIFF files (*.tif *.tiff)",
        )
        if not out_path:
            return
        if not out_path.lower().endswith((".tif", ".tiff")):
            out_path += ".tif"

        source_key = os.path.normcase(os.path.abspath(self.tiff_path))
        output_key = os.path.normcase(os.path.abspath(out_path))
        same_file = source_key == output_key
        if not same_file and os.path.exists(out_path):
            try:
                same_file = os.path.samefile(self.tiff_path, out_path)
            except OSError:
                pass
        if same_file:
            self.statusBar().showMessage(
                "Choose a different filename to preserve the original recording",
                5000,
            )
            return

        self.crop_progress.setRange(0, len(self.frames))
        self.crop_progress.setValue(0)
        self.crop_progress.setVisible(True)
        self.statusBar().showMessage("Exporting cropped TIFF stack...")
        self.roi_btn.setChecked(False)

        self.crop_thread = QThread(self)
        self.crop_worker = RoiStackExporter(
            self.tiff_path,
            os.path.abspath(out_path),
            bounds,
            self.frames[self.current_frame].shape,
        )
        self.crop_worker.moveToThread(self.crop_thread)
        self.crop_thread.started.connect(self.crop_worker.run)
        self.crop_worker.progress.connect(self._update_crop_progress)
        self.crop_worker.finished.connect(self._crop_finished)
        self.crop_worker.error.connect(self._crop_failed)
        self.crop_worker.canceled.connect(self._crop_canceled)
        self.crop_worker.finished.connect(self.crop_thread.quit)
        self.crop_worker.error.connect(self.crop_thread.quit)
        self.crop_worker.canceled.connect(self.crop_thread.quit)
        self.crop_thread.finished.connect(self.crop_worker.deleteLater)
        self.crop_thread.finished.connect(self._crop_thread_finished)
        self.crop_thread.finished.connect(self.crop_thread.deleteLater)
        self._crop_active = True
        self.crop_thread.start()
        self._refresh_roi_controls()

    def _crop_finished(self, output_path, frame_count):
        bounds = self._roi_frame_bounds()
        size_text = ""
        if bounds is not None:
            x0, y0, x1, y1 = bounds
            size_text = f", {x1 - x0}\u00d7{y1 - y0}px"
        self.statusBar().showMessage(
            f"Cropped TIFF saved: {os.path.basename(output_path)} "
            f"({frame_count} frames{size_text})",
            6000,
        )

    def _crop_failed(self, message):
        self.statusBar().showMessage(
            f"Cropped TIFF export failed: {message}",
            8000,
        )

    def _crop_canceled(self):
        self.statusBar().showMessage("Cropped TIFF export canceled", 3000)

    def _update_crop_progress(self, current, total):
        self.crop_progress.setMaximum(total)
        self.crop_progress.setValue(current)

    def _crop_thread_finished(self):
        self._crop_active = False
        self.crop_worker = None
        self.crop_thread = None
        self.crop_progress.setVisible(False)
        self._refresh_roi_controls()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.regenerate_frames()

    def closeEvent(self, event):
        if self._crop_is_running():
            self.crop_worker.stop()
            self.crop_thread.quit()
            if not self.crop_thread.wait(5000):
                self.statusBar().showMessage(
                    "Canceling cropped TIFF export; please wait before closing",
                    5000,
                )
                event.ignore()
                return
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = PlaybackWindow()
    win.showMaximized()
    sys.exit(app.exec_())
