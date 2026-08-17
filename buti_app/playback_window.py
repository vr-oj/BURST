import sys
import os
import csv
import tempfile
from collections import OrderedDict
import numpy as np
from PyQt5.QtCore import (
    Qt,
    QTimer,
    QThread,
    QObject,
    pyqtSignal,
    pyqtSlot,
    QRectF,
    QEventLoop,
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
    QMessageBox,
    QFrame,
    QGridLayout,
    QListWidget,
    QSizePolicy,
)
from tifffile import TiffFile, TiffWriter
from PIL import Image

from utils.roi import (
    bounds_to_normalized_roi,
    normalized_roi_to_bounds,
    pixel_roi_to_bounds,
)
from utils.tiff_crop import CropCanceled, export_cropped_tiff
from utils.recording_files import find_recording_csv_for_tiff
from ui.style_constants import PANEL_STYLESHEET


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
    """Load only the playback index and first frame in a worker thread."""

    progress = pyqtSignal(int, int)
    loaded = pyqtSignal(object, object, int)
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
                if total == 0:
                    raise ValueError("The TIFF does not contain any frames.")
                first_frame = tif.pages[0].asarray()
                self.loaded.emit(forces, first_frame, total)
                self.progress.emit(total, total)
        except Exception as e:
            self.error.emit(str(e))

        self.finished.emit(total)


class TiffFrameSequence:
    """Random-access TIFF pages with a small, bounded in-memory cache."""

    def __init__(
        self,
        path,
        total,
        first_frame=None,
        cache_size=5,
        cache_bytes=128 * 1024 * 1024,
    ):
        self.path = os.path.abspath(path)
        self._tiff = TiffFile(self.path)
        self._total = min(int(total), len(self._tiff.pages))
        self._cache_size = max(1, int(cache_size))
        self._cache_byte_limit = max(1, int(cache_bytes))
        self._cached_bytes = 0
        self._cache = OrderedDict()
        if first_frame is not None and self._total:
            self._cache[0] = first_frame
            self._cached_bytes = int(first_frame.nbytes)

    def __len__(self):
        return self._total

    def __bool__(self):
        return self._total > 0

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[item] for item in range(*index.indices(self._total))]
        index = int(index)
        if index < 0:
            index += self._total
        if not 0 <= index < self._total:
            raise IndexError(index)
        if index in self._cache:
            frame = self._cache.pop(index)
            self._cache[index] = frame
            return frame

        frame = self._tiff.pages[index].asarray()
        self._cache[index] = frame
        self._cached_bytes += int(frame.nbytes)
        while len(self._cache) > 1 and (
            len(self._cache) > self._cache_size
            or self._cached_bytes > self._cache_byte_limit
        ):
            _, old_frame = self._cache.popitem(last=False)
            self._cached_bytes -= int(old_frame.nbytes)
        return frame

    def __iter__(self):
        for index in range(self._total):
            yield self[index]

    def clear(self):
        self._cache.clear()
        self._cached_bytes = 0
        self._total = 0
        self._tiff.close()


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


class BatchRoiStackExporter(QObject):
    """Apply one source-pixel ROI to a sequence of TIFF recordings."""

    progress = pyqtSignal(int, int)
    finished = pyqtSignal(object, object)
    canceled = pyqtSignal()

    def __init__(self, jobs, bounds, parent=None):
        super().__init__(parent)
        self.jobs = list(jobs)
        self.bounds = bounds
        self._abort = False

    def stop(self):
        self._abort = True

    @pyqtSlot()
    def run(self):
        completed = []
        failures = []
        total = len(self.jobs)
        for index, (source_path, output_path, source_shape) in enumerate(self.jobs):
            if self._abort:
                self.canceled.emit()
                return
            try:
                frame_count = export_cropped_tiff(
                    source_path,
                    output_path,
                    self.bounds,
                    source_shape,
                    should_cancel=lambda: self._abort,
                )
                completed.append((output_path, frame_count))
            except CropCanceled:
                self.canceled.emit()
                return
            except Exception as exc:
                failures.append((source_path, str(exc)))
            self.progress.emit(index + 1, total)
        self.finished.emit(completed, failures)


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

    def set_normalized_roi(self, roi):
        """Display an ROI supplied in normalized image coordinates."""

        if roi is None:
            self.clear_roi()
            return
        image_rect = self.pixmap_item.boundingRect()
        if image_rect.isEmpty():
            return

        left, top, right, bottom = (float(value) for value in roi)
        rect = QRectF(
            left * image_rect.width(),
            top * image_rect.height(),
            (right - left) * image_rect.width(),
            (bottom - top) * image_rect.height(),
        ).intersected(image_rect)
        if rect.isEmpty():
            self.clear_roi()
            return

        if self._roi_item is None:
            self._roi_item = QGraphicsRectItem()
            pen = QPen(Qt.red)
            pen.setWidth(2)
            pen.setCosmetic(True)
            self._roi_item.setPen(pen)
            self._roi_item.setZValue(2)
            self.scene().addItem(self._roi_item)
        self._roi_item.setRect(rect)
        self._normalized_roi = (
            rect.left() / image_rect.width(),
            rect.top() / image_rect.height(),
            rect.right() / image_rect.width(),
            rect.bottom() / image_rect.height(),
        )
        self.roi_changed.emit(rect)

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


class PlaybackWindow(QMainWindow):
    """Display a TIFF stack with optional force overlay and playback controls."""

    def __init__(self, tiff_path=None, csv_path=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Playback")
        self.resize(1200, 800)

        self.frames = []
        self.forces = []
        self._pixmap_cache = OrderedDict()
        self._pixmap_cache_size = 12
        self.loader_thread = None
        self.loader = None
        self.crop_thread = None
        self.crop_worker = None
        self.tiff_path = None
        self.csv_path = None
        self._crop_active = False
        self._batch_skipped = []
        self._batch_source_paths = []
        self.current_frame = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame)
        self.resize_render_timer = QTimer(self)
        self.resize_render_timer.setSingleShot(True)
        self.resize_render_timer.timeout.connect(self.regenerate_frames)

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
        self.play_btn.setProperty("cssClass", "primary")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setProperty("cssClass", "controlSlider")
        self.slider.setTracking(False)
        self.slider.setEnabled(False)
        self.frame_label = QLabel("0/0")

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 1000)
        self.fps_spin.setValue(10)
        self.fps_spin.setProperty("cssClass", "monoInput")
        self.fps_spin.valueChanged.connect(self.update_fps)

        self.font_spin = QSpinBox()
        self.font_spin.setRange(10, 200)
        self.font_spin.setValue(10)
        self.font_spin.setProperty("cssClass", "monoInput")
        self.font_spin.valueChanged.connect(self._update_overlay)

        self.overlay_cb = QCheckBox("Show Overlay")
        self.overlay_cb.setProperty("cssClass", "muted")
        self.overlay_cb.setChecked(True)
        self.overlay_cb.toggled.connect(self._update_overlay)

        self.roi_btn = QPushButton("Draw ROI")
        self.roi_btn.setObjectName("roiDrawButton")
        self.roi_btn.setCheckable(True)
        self.roi_btn.setProperty("cssClass", "primary")
        self.roi_btn.setToolTip("Select, then drag over the image to define a crop")
        self.clear_roi_btn = QPushButton("Clear ROI")
        self.clear_roi_btn.setProperty("cssClass", "ghost")
        self.roi_x_spin = QSpinBox()
        self.roi_y_spin = QSpinBox()
        self.roi_width_spin = QSpinBox()
        self.roi_height_spin = QSpinBox()
        for spin in (
            self.roi_x_spin,
            self.roi_y_spin,
            self.roi_width_spin,
            self.roi_height_spin,
        ):
            spin.setSuffix(" px")
            spin.setMinimumWidth(82)
            spin.setEnabled(False)
            spin.setProperty("cssClass", "monoInput")
        self.roi_x_spin.setRange(0, 0)
        self.roi_y_spin.setRange(0, 0)
        self.roi_width_spin.setRange(1, 1)
        self.roi_height_spin.setRange(1, 1)
        self.apply_roi_btn = QPushButton("Apply ROI")
        self.apply_roi_btn.setProperty("cssClass", "ghost")
        self.apply_roi_btn.setToolTip(
            "Apply these exact source-pixel coordinates to the ROI"
        )
        self.export_roi_btn = QPushButton("Export ROI PNG")
        self.export_roi_btn.setProperty("cssClass", "ghost")
        self.export_roi_stack_btn = QPushButton("Export Cropped TIFF")
        self.export_roi_stack_btn.setProperty("cssClass", "primary")
        self.export_roi_stack_btn.setToolTip(
            "Crop this ROI from every frame into a new TIFF stack"
        )
        self.batch_export_roi_stack_btn = QPushButton("Crop Selected TIFFs")
        self.batch_export_roi_stack_btn.setProperty("cssClass", "primary")
        self.batch_export_roi_stack_btn.setToolTip(
            "Apply these exact ROI coordinates to multiple TIFF recordings"
        )

        self.export_btn = QPushButton("💾 Export Overlay TIFF")
        self.export_btn.setProperty("cssClass", "primary")
        self.snapshot_btn = QPushButton("🖼 Export Frame PNG")
        self.snapshot_btn.setProperty("cssClass", "ghost")

        self.select_batch_tiffs_btn = QPushButton("Add TIFFs…")
        self.select_batch_tiffs_btn.setProperty("cssClass", "ghost")
        self.select_batch_tiffs_btn.setToolTip(
            "Add recordings to the shared-ROI batch queue (maximum 5)"
        )
        self.clear_batch_tiffs_btn = QPushButton("Clear List")
        self.clear_batch_tiffs_btn.setProperty("cssClass", "ghost")
        self.batch_selection_label = QLabel("0 of 5 TIFFs selected")
        self.batch_selection_label.setProperty("cssClass", "detailLabel")
        self.batch_file_list = QListWidget()
        self.batch_file_list.setProperty("cssClass", "batchList")
        self.batch_file_list.setMaximumHeight(82)
        self.batch_file_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.batch_file_list.setToolTip("Double-click a recording to remove it")

        scrubber_card = QFrame()
        scrubber_card.setProperty("cssClass", "panelCard")
        controls_layout = QHBoxLayout(scrubber_card)
        controls_layout.setContentsMargins(10, 8, 10, 8)
        controls_layout.setSpacing(10)
        controls_layout.addWidget(self.play_btn)
        controls_layout.addWidget(self.slider, stretch=1)
        controls_layout.addWidget(self.frame_label)

        playback_card = QFrame()
        playback_card.setProperty("cssClass", "panelCard")
        playback_layout = QVBoxLayout(playback_card)
        playback_layout.setContentsMargins(12, 10, 12, 10)
        playback_layout.setSpacing(8)
        playback_title = QLabel("Playback & Export")
        playback_title.setProperty("cssClass", "panelTitle")
        playback_layout.addWidget(playback_title)
        options_grid = QGridLayout()
        options_grid.setHorizontalSpacing(8)
        options_grid.setVerticalSpacing(6)
        options_grid.addWidget(QLabel("Playback FPS"), 0, 0)
        options_grid.addWidget(self.fps_spin, 0, 1)
        options_grid.addWidget(QLabel("Overlay Font"), 1, 0)
        options_grid.addWidget(self.font_spin, 1, 1)
        options_grid.addWidget(self.overlay_cb, 2, 0, 1, 2)
        playback_layout.addLayout(options_grid)
        playback_actions = QHBoxLayout()
        playback_actions.addWidget(self.snapshot_btn)
        playback_actions.addWidget(self.export_btn)
        playback_layout.addLayout(playback_actions)

        roi_card = QFrame()
        roi_card.setProperty("cssClass", "panelCard")
        roi_card_layout = QVBoxLayout(roi_card)
        roi_card_layout.setContentsMargins(12, 10, 12, 10)
        roi_card_layout.setSpacing(8)
        roi_header = QHBoxLayout()
        roi_title = QLabel("Shared ROI")
        roi_title.setProperty("cssClass", "panelTitle")
        roi_header.addWidget(roi_title)
        roi_header.addStretch()
        roi_hint = QLabel("Source-pixel coordinates")
        roi_hint.setProperty("cssClass", "detailLabel")
        roi_header.addWidget(roi_hint)
        roi_card_layout.addLayout(roi_header)
        roi_actions = QHBoxLayout()
        roi_actions.setSpacing(6)
        roi_actions.addWidget(self.roi_btn)
        roi_actions.addWidget(self.clear_roi_btn)
        roi_actions.addStretch()
        roi_card_layout.addLayout(roi_actions)
        roi_grid = QGridLayout()
        roi_grid.setHorizontalSpacing(6)
        for column, (label_text, spin) in enumerate(
            (("X", self.roi_x_spin), ("Y", self.roi_y_spin),
             ("Width", self.roi_width_spin), ("Height", self.roi_height_spin))
        ):
            roi_grid.addWidget(QLabel(label_text), 0, column)
            roi_grid.addWidget(spin, 1, column)
        roi_grid.addWidget(self.apply_roi_btn, 1, 4)
        roi_card_layout.addLayout(roi_grid)
        roi_exports = QHBoxLayout()
        roi_exports.addStretch()
        roi_exports.addWidget(self.export_roi_btn)
        roi_exports.addWidget(self.export_roi_stack_btn)
        roi_card_layout.addLayout(roi_exports)

        batch_card = QFrame()
        batch_card.setProperty("cssClass", "panelCard")
        batch_layout = QVBoxLayout(batch_card)
        batch_layout.setContentsMargins(12, 10, 12, 10)
        batch_layout.setSpacing(8)
        batch_header = QHBoxLayout()
        batch_title = QLabel("Batch Crop")
        batch_title.setProperty("cssClass", "panelTitle")
        batch_header.addWidget(batch_title)
        batch_header.addStretch()
        batch_header.addWidget(self.batch_selection_label)
        batch_layout.addLayout(batch_header)
        batch_layout.addWidget(self.batch_file_list)
        batch_actions = QHBoxLayout()
        batch_actions.addWidget(self.select_batch_tiffs_btn)
        batch_actions.addWidget(self.clear_batch_tiffs_btn)
        batch_actions.addStretch()
        batch_actions.addWidget(self.batch_export_roi_stack_btn)
        batch_layout.addLayout(batch_actions)

        tool_cards_layout = QHBoxLayout()
        tool_cards_layout.setContentsMargins(0, 0, 0, 0)
        tool_cards_layout.setSpacing(8)
        tool_cards_layout.addWidget(playback_card, 2)
        tool_cards_layout.addWidget(roi_card, 4)
        tool_cards_layout.addWidget(batch_card, 3)

        layout = QVBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        layout.addWidget(self.view, stretch=1)
        layout.addWidget(self.progress)
        layout.addWidget(self.crop_progress)
        layout.addWidget(scrubber_card)
        layout.addLayout(tool_cards_layout)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # ─── Signals ──────────────────────────────────────────────────────
        self.play_btn.clicked.connect(self._toggle_play)
        self.slider.valueChanged.connect(self.set_frame)
        self.export_btn.clicked.connect(self.export_overlay)
        self.snapshot_btn.clicked.connect(self.export_snapshot)
        self.roi_btn.toggled.connect(self.toggle_roi_mode)
        self.clear_roi_btn.clicked.connect(self.clear_roi)
        self.apply_roi_btn.clicked.connect(self.apply_manual_roi)
        self.export_roi_btn.clicked.connect(self.export_roi)
        self.export_roi_stack_btn.clicked.connect(self.export_roi_stack)
        self.batch_export_roi_stack_btn.clicked.connect(self.export_roi_stack_batch)
        self.select_batch_tiffs_btn.clicked.connect(self.select_batch_tiffs)
        self.clear_batch_tiffs_btn.clicked.connect(self.clear_batch_tiffs)
        self.batch_file_list.itemDoubleClicked.connect(self._remove_batch_item)
        self.view.roi_changed.connect(self._on_roi_changed)
        self.view.roi_finished.connect(self._finish_roi_drawing)

        self.clear_roi_btn.setEnabled(False)
        self.apply_roi_btn.setEnabled(False)
        self.export_roi_btn.setEnabled(False)
        self.export_roi_stack_btn.setEnabled(False)
        self.batch_export_roi_stack_btn.setEnabled(False)
        self.clear_batch_tiffs_btn.setEnabled(False)
        self.setStyleSheet(PANEL_STYLESHEET)

        if tiff_path:
            resolved_csv = csv_path or find_recording_csv_for_tiff(tiff_path)
            if resolved_csv:
                self.load_files(tiff_path, resolved_csv)
            else:
                self._show_missing_pair(tiff_path)
        else:
            self.pick_files()

    # ─── File Loading ─────────────────────────────────────────────────────
    def pick_files(self):
        tiff, _ = QFileDialog.getOpenFileName(
            self, "Open BURST TIFF Recording", "", "TIFF files (*.tif *.tiff)"
        )
        if not tiff:
            return
        csv_path = find_recording_csv_for_tiff(tiff)
        if not csv_path:
            self._show_missing_pair(tiff)
            return
        self.load_files(tiff, csv_path)

    def _show_missing_pair(self, tiff_path):
        QMessageBox.warning(
            self,
            "Paired CSV Not Found",
            "BURST could not identify the synchronized CSV beside:\n\n"
            f"{os.path.basename(tiff_path)}\n\n"
            "Keep the matching *_force.csv in the same folder as the *_video.tif.",
        )

    def load_files(self, tiff_path, csv_path):
        # Show progress bar and start worker thread to avoid blocking UI
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.statusBar().showMessage("Loading files...")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        self.frames.clear()
        self.frames = []
        self._pixmap_cache.clear()
        self.forces.clear()
        self.view.clear_roi()
        self.tiff_path = os.path.abspath(tiff_path)
        self.csv_path = os.path.abspath(csv_path)
        self._set_batch_sources([self.tiff_path])

        self.loader_thread = QThread(self)
        self.loader = PlaybackLoader(tiff_path, csv_path)
        self.loader.moveToThread(self.loader_thread)
        self.loader_thread.started.connect(self.loader.run)
        self.loader.progress.connect(self._update_progress)
        self.loader.loaded.connect(self._on_playback_loaded)
        self.loader.finished.connect(self._loading_finished)
        self.loader.error.connect(self._show_error)
        self.loader.finished.connect(self.loader_thread.quit)
        self.loader_thread.finished.connect(self.loader.deleteLater)
        self.loader_thread.finished.connect(self._loader_thread_finished)
        self.loader_thread.finished.connect(self.loader_thread.deleteLater)
        self.loader_thread.start()

    def _loader_thread_finished(self):
        self.loader = None
        self.loader_thread = None

    def _set_batch_sources(self, paths):
        """Replace the visible batch queue with up to five unique TIFF files."""

        unique_paths = []
        seen = set()
        for path in paths:
            absolute = os.path.abspath(path)
            if not absolute.lower().endswith((".tif", ".tiff")):
                continue
            key = os.path.normcase(os.path.realpath(absolute))
            if key in seen:
                continue
            seen.add(key)
            unique_paths.append(absolute)

        overflow = max(0, len(unique_paths) - 5)
        self._batch_source_paths = unique_paths[:5]
        self.batch_file_list.clear()
        for path in self._batch_source_paths:
            self.batch_file_list.addItem(os.path.basename(path))
            self.batch_file_list.item(self.batch_file_list.count() - 1).setToolTip(path)
        count = len(self._batch_source_paths)
        self.batch_selection_label.setText(f"{count} of 5 TIFFs selected")
        self.batch_file_list.setToolTip("\n".join(self._batch_source_paths))
        self.clear_batch_tiffs_btn.setEnabled(bool(count) and not self._crop_is_running())
        self._refresh_roi_controls()
        return overflow

    def select_batch_tiffs(self):
        """Add TIFF recordings to the shared-ROI queue, capped at five."""

        start_dir = os.path.dirname(self.tiff_path) if self.tiff_path else ""
        source_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add TIFF Recordings for Shared-ROI Batch Crop (Maximum 5)",
            start_dir,
            "TIFF files (*.tif *.tiff)",
        )
        if not source_paths:
            return False
        overflow = self._set_batch_sources(self._batch_source_paths + source_paths)
        if overflow:
            QMessageBox.information(
                self,
                "Five-File Limit",
                f"The first five unique TIFF recordings were kept; {overflow} additional file(s) were not added.",
            )
        return True

    def clear_batch_tiffs(self):
        self._set_batch_sources([])

    def _remove_batch_item(self, item):
        row = self.batch_file_list.row(item)
        if 0 <= row < len(self._batch_source_paths):
            paths = list(self._batch_source_paths)
            paths.pop(row)
            self._set_batch_sources(paths)

    def _update_progress(self, current, total):
        self.progress.setMaximum(total)
        self.progress.setValue(current)

    def _on_playback_loaded(self, forces, first_frame, total_frames):
        self.frames = TiffFrameSequence(
            self.tiff_path,
            total_frames,
            first_frame=first_frame,
        )
        self.forces = list(forces[:total_frames])
        if len(self.forces) < total_frames:
            self.forces.extend([0.0] * (total_frames - len(self.forces)))
        self.current_frame = 0
        self.slider.setRange(0, max(0, total_frames - 1))
        self.slider.setEnabled(True)
        self.play_btn.setEnabled(True)
        self._configure_roi_fields(first_frame.shape)
        self._refresh_roi_controls()
        self.show_frame()

    def _loading_finished(self, _total_frames):
        QApplication.restoreOverrideCursor()
        self.statusBar().clearMessage()
        self.progress.setVisible(False)
        if self.frames:
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
        label_w = max(1, self.view.viewport().width())
        label_h = max(1, self.view.viewport().height())
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

    def regenerate_frames(self):
        """Invalidate scaled previews and redraw only the current frame."""
        self._pixmap_cache.clear()
        if self.frames:
            self.show_frame()

    def show_frame(self):
        if not self.frames:
            return
        viewport_size = (
            max(1, self.view.viewport().width()),
            max(1, self.view.viewport().height()),
        )
        cache_key = (self.current_frame,) + viewport_size
        pixmap = self._pixmap_cache.pop(cache_key, None)
        if pixmap is None:
            frame = self.frames[self.current_frame]
            force = self.forces[self.current_frame]
            pixmap = self.render_pixmap(
                frame,
                force,
                self.current_frame,
                len(self.frames),
            )
        self._pixmap_cache[cache_key] = pixmap
        while len(self._pixmap_cache) > self._pixmap_cache_size:
            self._pixmap_cache.popitem(last=False)
        self.view.set_pixmap(pixmap)
        if self.slider.maximum() != len(self.frames) - 1:
            self.slider.setRange(0, max(0, len(self.frames) - 1))
        self.slider.blockSignals(True)
        self.slider.setValue(self.current_frame)
        self.slider.blockSignals(False)
        self.frame_label.setText(f"{self.current_frame + 1}/{len(self.frames)}")
        force = self.forces[self.current_frame]
        scale_factor = pixmap.height() / 500
        font_size = int(self.font_spin.value() * scale_factor)
        frame_text = (
            f"{self.current_frame + 1}/{len(self.frames)}"
            if self.overlay_cb.isChecked()
            else ""
        )
        self.view.update_overlay(
            force,
            frame_text,
            font_size,
            self.overlay_cb.isChecked(),
        )

    def _update_overlay(self):
        if self.frames:
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
        if not out_path.lower().endswith((".tif", ".tiff")):
            out_path += ".tif"
        if self.tiff_path and os.path.normcase(
            os.path.realpath(out_path)
        ) == os.path.normcase(os.path.realpath(self.tiff_path)):
            self.statusBar().showMessage(
                "Choose a different filename to preserve the original recording",
                5000,
            )
            return

        self.statusBar().showMessage("Exporting overlay...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.export_btn.setEnabled(False)
        base_font = self.font_spin.value()
        preview_size = (
            max(1, self.view.viewport().width()),
            max(1, self.view.viewport().height()),
        )
        total = len(self.frames)
        self.progress.setFormat("Exporting frame %v of %m")
        self.progress.setRange(0, total)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setVisible(True)
        output_dir = os.path.dirname(os.path.abspath(out_path))
        temp_path = None
        try:
            temp_file = tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".burst-overlay-",
                suffix=".tif",
                dir=output_dir,
                delete=False,
            )
            temp_path = temp_file.name
            temp_file.close()
            with TiffWriter(temp_path, bigtiff=True) as output_tiff:
                for idx, (frame, force) in enumerate(zip(self.frames, self.forces)):
                    overlaid = self.overlay_frame(
                        frame,
                        force,
                        base_font,
                        idx,
                        total,
                        preview_size=preview_size,
                    )
                    output_tiff.write(overlaid, photometric="minisblack")
                    self.progress.setValue(idx + 1)
                    QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
            os.replace(temp_path, out_path)
            temp_path = None
            self.statusBar().showMessage(
                f"Saved: {os.path.basename(out_path)}", 3000
            )
        except Exception as exc:
            self.statusBar().showMessage(f"Overlay export failed: {exc}", 8000)
        finally:
            if temp_path:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            QApplication.restoreOverrideCursor()
            self.export_btn.setEnabled(True)
            self.progress.setVisible(False)
            self.progress.setTextVisible(False)

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
    def _configure_roi_fields(self, frame_shape):
        frame_height, frame_width = int(frame_shape[0]), int(frame_shape[1])
        self.roi_x_spin.setRange(0, max(0, frame_width - 1))
        self.roi_y_spin.setRange(0, max(0, frame_height - 1))
        self.roi_width_spin.setRange(1, max(1, frame_width))
        self.roi_height_spin.setRange(1, max(1, frame_height))
        self.roi_x_spin.setValue(0)
        self.roi_y_spin.setValue(0)
        self.roi_width_spin.setValue(max(1, frame_width))
        self.roi_height_spin.setValue(max(1, frame_height))

    def _update_roi_fields(self, bounds):
        if bounds is None:
            return
        x0, y0, x1, y1 = bounds
        self.roi_x_spin.setValue(x0)
        self.roi_y_spin.setValue(y0)
        self.roi_width_spin.setValue(x1 - x0)
        self.roi_height_spin.setValue(y1 - y0)

    def apply_manual_roi(self):
        if not self.frames:
            return
        try:
            bounds = pixel_roi_to_bounds(
                self.roi_x_spin.value(),
                self.roi_y_spin.value(),
                self.roi_width_spin.value(),
                self.roi_height_spin.value(),
                self.frames[self.current_frame].shape,
            )
        except ValueError as exc:
            self.statusBar().showMessage(str(exc), 5000)
            return

        normalized = bounds_to_normalized_roi(
            bounds,
            self.frames[self.current_frame].shape,
        )
        self.view.set_normalized_roi(normalized)
        self.roi_btn.setChecked(False)
        x0, y0, x1, y1 = bounds
        self.statusBar().showMessage(
            f"ROI applied: {x1 - x0}×{y1 - y0} px at ({x0}, {y0})"
        )

    def clear_roi(self):
        self.roi_btn.setChecked(False)
        self.view.clear_roi()
        self.statusBar().showMessage(
            "ROI cleared; the pixel values are retained for reuse", 3000
        )

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
        has_frames = bool(self.frames)
        self.roi_btn.setEnabled(has_frames and not busy)
        self.clear_roi_btn.setEnabled(has_roi and not busy)
        self.apply_roi_btn.setEnabled(has_frames and not busy)
        for spin in (
            self.roi_x_spin,
            self.roi_y_spin,
            self.roi_width_spin,
            self.roi_height_spin,
        ):
            spin.setEnabled(has_frames and not busy)
        self.export_roi_btn.setEnabled(has_roi and not busy)
        self.export_roi_stack_btn.setEnabled(has_roi and not busy)
        # Keep this available with a valid ROI: an empty queue is populated by
        # the capped five-TIFF picker when the user clicks the action.
        self.batch_export_roi_stack_btn.setEnabled(has_roi and not busy)
        self.select_batch_tiffs_btn.setEnabled(not busy and len(self._batch_source_paths) < 5)
        self.clear_batch_tiffs_btn.setEnabled(bool(self._batch_source_paths) and not busy)
        self.batch_file_list.setEnabled(not busy)

    def _on_roi_changed(self, _rect):
        self._refresh_roi_controls()
        bounds = self._roi_frame_bounds()
        if bounds is not None:
            self._update_roi_fields(bounds)
            x0, y0, x1, y1 = bounds
            self.statusBar().showMessage(
                f"ROI: {x1 - x0}\u00d7{y1 - y0} px at ({x0}, {y0})"
            )

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

    def export_roi_stack_batch(self):
        """Crop selected recordings with the exact current source-pixel ROI."""

        bounds = self._roi_frame_bounds()
        if bounds is None or self._crop_is_running():
            self.statusBar().showMessage("Draw or apply an ROI first", 2000)
            return

        source_paths = list(self._batch_source_paths[:5])
        if not source_paths:
            if not self.select_batch_tiffs():
                return
            source_paths = list(self._batch_source_paths[:5])

        jobs = []
        skipped = []
        seen = set()
        x0, y0, x1, y1 = bounds
        for source_path in source_paths:
            source_path = os.path.abspath(source_path)
            source_key = os.path.normcase(os.path.realpath(source_path))
            if source_key in seen:
                continue
            seen.add(source_key)

            source_stem, _ = os.path.splitext(source_path)
            output_path = f"{source_stem}_cropped.tif"
            if os.path.exists(output_path):
                skipped.append(
                    (source_path, f"{os.path.basename(output_path)} already exists")
                )
                continue

            try:
                with TiffFile(source_path) as source_tiff:
                    if not source_tiff.pages:
                        raise ValueError("TIFF contains no frames")
                    source_shape = tuple(source_tiff.pages[0].shape)
                if len(source_shape) != 2:
                    raise ValueError("only grayscale TIFF frames are supported")
                pixel_roi_to_bounds(
                    x0,
                    y0,
                    x1 - x0,
                    y1 - y0,
                    source_shape,
                )
            except Exception as exc:
                skipped.append((source_path, str(exc)))
                continue
            jobs.append((source_path, output_path, source_shape))

        self._batch_skipped = skipped
        if not jobs:
            self.statusBar().showMessage(
                f"No files queued; {len(skipped)} file(s) skipped. "
                "Existing cropped TIFFs were not overwritten.",
                8000,
            )
            return

        self.crop_progress.setFormat("Cropping file %v of %m")
        self.crop_progress.setRange(0, len(jobs))
        self.crop_progress.setValue(0)
        self.crop_progress.setVisible(True)
        self.statusBar().showMessage(
            f"Batch cropping {len(jobs)} TIFF recording(s) with "
            f"ROI {x1 - x0}×{y1 - y0} at ({x0}, {y0})..."
        )
        self.roi_btn.setChecked(False)

        self.crop_thread = QThread(self)
        self.crop_worker = BatchRoiStackExporter(jobs, bounds)
        self.crop_worker.moveToThread(self.crop_thread)
        self.crop_thread.started.connect(self.crop_worker.run)
        self.crop_worker.progress.connect(self._update_crop_progress)
        self.crop_worker.finished.connect(self._batch_crop_finished)
        self.crop_worker.canceled.connect(self._crop_canceled)
        self.crop_worker.finished.connect(self.crop_thread.quit)
        self.crop_worker.canceled.connect(self.crop_thread.quit)
        self.crop_thread.finished.connect(self.crop_worker.deleteLater)
        self.crop_thread.finished.connect(self._crop_thread_finished)
        self.crop_thread.finished.connect(self.crop_thread.deleteLater)
        self._crop_active = True
        self.crop_thread.start()
        self._refresh_roi_controls()

    def _batch_crop_finished(self, completed, failures):
        skipped_count = len(self._batch_skipped)
        failed_count = len(failures)
        self.statusBar().showMessage(
            f"Batch crop complete: {len(completed)} saved, "
            f"{skipped_count} skipped, {failed_count} failed. "
            "Original TIFFs were unchanged.",
            10000,
        )
        if failures:
            details = "\n".join(
                f"{os.path.basename(path)}: {message}"
                for path, message in failures[:8]
            )
            QMessageBox.warning(
                self,
                "Batch Crop Incomplete",
                f"{failed_count} TIFF file(s) could not be cropped:\n\n{details}",
            )

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
        self.crop_progress.setFormat("Cropping frame %v of %m")
        self._refresh_roi_controls()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resize_render_timer.start(75)

    def closeEvent(self, event):
        if self.loader_thread is not None:
            try:
                if self.loader_thread.isRunning():
                    self.loader_thread.quit()
                    if not self.loader_thread.wait(5000):
                        self.statusBar().showMessage(
                            "Finishing the current TIFF frame read; please wait",
                            5000,
                        )
                        event.ignore()
                        return
            except RuntimeError:
                self.loader_thread = None
                self.loader = None
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
        if hasattr(self.frames, "clear"):
            self.frames.clear()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = PlaybackWindow()
    win.showMaximized()
    sys.exit(app.exec_())
