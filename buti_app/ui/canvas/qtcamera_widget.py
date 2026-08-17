from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QImage, QPainter, QPen
from PyQt5.QtWidgets import QOpenGLWidget
from OpenGL.GL import glClearColor

from utils.frame_transform import transform_qimage


class QtCameraWidget(QOpenGLWidget):
    """Live camera view with lossless crop selection and mirrored display."""

    roi_changed = pyqtSignal(object)
    roi_edit_finished = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_qimage = None
        self._normalized_roi = None
        self._mirror_horizontal = False
        self._mirror_vertical = False
        self._roi_editing = False
        self._drag_start = None
        self._drag_end = None
        self.setMouseTracking(True)

    def initializeGL(self):
        glClearColor(0.0, 0.0, 0.0, 1.0)

    @pyqtSlot(QImage, object)
    def _on_frame_ready(self, qimg: QImage, raw_buffer):
        del raw_buffer
        self._current_qimage = qimg.copy()
        self.update()

    def clear_image(self):
        self._current_qimage = None
        self.update()

    def normalized_roi(self):
        return self._normalized_roi

    def source_size(self):
        if self._current_qimage is None:
            return None
        return self._current_qimage.width(), self._current_qimage.height()

    def set_mirroring(self, horizontal: bool, vertical: bool) -> None:
        self._mirror_horizontal = bool(horizontal)
        self._mirror_vertical = bool(vertical)
        self.update()

    def begin_roi_edit(self) -> bool:
        if self._current_qimage is None:
            return False
        self._roi_editing = True
        self._drag_start = None
        self._drag_end = None
        self.setCursor(Qt.CrossCursor)
        self.update()
        return True

    def cancel_roi_edit(self) -> None:
        self._roi_editing = False
        self._drag_start = None
        self._drag_end = None
        self.unsetCursor()
        self.update()

    def clear_roi(self) -> None:
        self.cancel_roi_edit()
        self._normalized_roi = None
        self.roi_changed.emit(None)
        self.update()

    def _display_qimage(self):
        if self._current_qimage is None:
            return None
        roi = None if self._roi_editing else self._normalized_roi
        image, _metadata = transform_qimage(
            self._current_qimage,
            roi,
            mirror_horizontal=self._mirror_horizontal,
            mirror_vertical=self._mirror_vertical,
        )
        return image

    def _image_target_rect(self, image) -> QRectF:
        if image is None or image.width() <= 0 or image.height() <= 0:
            return QRectF()
        scale = min(self.width() / image.width(), self.height() / image.height())
        width = image.width() * scale
        height = image.height() * scale
        return QRectF(
            (self.width() - width) / 2.0,
            (self.height() - height) / 2.0,
            width,
            height,
        )

    def paintGL(self):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.black)
        image = self._display_qimage()
        if image is not None:
            target = self._image_target_rect(image)
            painter.drawImage(target, image, QRectF(image.rect()))
            if self._roi_editing:
                overlay = self._active_display_roi(target)
                if overlay is not None:
                    painter.setPen(QPen(Qt.green, 2, Qt.SolidLine))
                    painter.drawRect(overlay)
        painter.end()

    def _active_display_roi(self, target: QRectF):
        if self._drag_start is not None and self._drag_end is not None:
            return QRectF(self._drag_start, self._drag_end).normalized().intersected(
                target
            )
        if self._normalized_roi is None:
            return None
        left, top, right, bottom = self._normalized_roi
        if self._mirror_horizontal:
            left, right = 1.0 - right, 1.0 - left
        if self._mirror_vertical:
            top, bottom = 1.0 - bottom, 1.0 - top
        return QRectF(
            target.left() + left * target.width(),
            target.top() + top * target.height(),
            (right - left) * target.width(),
            (bottom - top) * target.height(),
        )

    def _clamp_to_full_image(self, point) -> QPointF | None:
        if self._current_qimage is None:
            return None
        full_image, _ = transform_qimage(
            self._current_qimage,
            None,
            mirror_horizontal=self._mirror_horizontal,
            mirror_vertical=self._mirror_vertical,
        )
        target = self._image_target_rect(full_image)
        if target.isEmpty():
            return None
        return QPointF(
            max(target.left(), min(target.right(), point.x())),
            max(target.top(), min(target.bottom(), point.y())),
        )

    def mousePressEvent(self, event):
        if self._roi_editing and event.button() == Qt.LeftButton:
            point = self._clamp_to_full_image(event.pos())
            if point is not None:
                self._drag_start = point
                self._drag_end = point
                self.update()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._roi_editing and self._drag_start is not None:
            self._drag_end = self._clamp_to_full_image(event.pos())
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if (
            self._roi_editing
            and event.button() == Qt.LeftButton
            and self._drag_start is not None
        ):
            self._drag_end = self._clamp_to_full_image(event.pos())
            self._commit_dragged_roi()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _commit_dragged_roi(self) -> None:
        if (
            self._current_qimage is None
            or self._drag_start is None
            or self._drag_end is None
        ):
            self.cancel_roi_edit()
            return
        full_image, _ = transform_qimage(
            self._current_qimage,
            None,
            mirror_horizontal=self._mirror_horizontal,
            mirror_vertical=self._mirror_vertical,
        )
        target = self._image_target_rect(full_image)
        rect = QRectF(self._drag_start, self._drag_end).normalized().intersected(target)
        if rect.width() < 2 or rect.height() < 2:
            self.cancel_roi_edit()
            return
        left = (rect.left() - target.left()) / target.width()
        right = (rect.right() - target.left()) / target.width()
        top = (rect.top() - target.top()) / target.height()
        bottom = (rect.bottom() - target.top()) / target.height()
        if self._mirror_horizontal:
            left, right = 1.0 - right, 1.0 - left
        if self._mirror_vertical:
            top, bottom = 1.0 - bottom, 1.0 - top
        self._normalized_roi = (left, top, right, bottom)
        self._roi_editing = False
        self._drag_start = None
        self._drag_end = None
        self.unsetCursor()
        self.roi_changed.emit(self._normalized_roi)
        self.roi_edit_finished.emit(self._normalized_roi)
        self.update()
