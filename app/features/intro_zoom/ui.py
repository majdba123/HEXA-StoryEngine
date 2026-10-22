"""Small desktop-only selector. The render backend never imports Qt."""
from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

from app.features.intro_zoom.geometry import click_to_source, fitted_rect
from app.features.intro_zoom.models import IntroZoomConfig, PreparedIntro
from app.features.intro_zoom.render import preview_frame
from app.features.intro_zoom.validation import open_image, probe_voice


def _qimage(image: Image.Image) -> QImage:
    rgb = image.convert("RGB")
    return QImage(rgb.tobytes(), rgb.width, rgb.height, rgb.width * 3,
                  QImage.Format.Format_RGB888).copy()


class ImageSelector(QWidget):
    selected = Signal(float, float)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(520, 340)
        self.image: QImage | None = None
        self.source_size: tuple[int, int] | None = None
        self.focus: tuple[float, float] | None = None

    def set_source(self, image: Image.Image) -> None:
        self.source_size = image.size
        sample = image.copy()
        sample.thumbnail((1600, 1200), Image.Resampling.LANCZOS)
        self.image = _qimage(sample)
        sample.close()
        self.focus = None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101318"))
        if self.image is None or self.source_size is None:
            return
        area = fitted_rect(self.width(), self.height(), *self.source_size)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(QRectF(area.x, area.y, area.width, area.height), self.image)
        if self.focus is not None:
            x = area.x + self.focus[0] * area.width
            y = area.y + self.focus[1] * area.height
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.setBrush(QColor("#ff5b50"))
            painter.drawEllipse(round(x - 8), round(y - 8), 16, 16)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.image is None or self.source_size is None:
            return
        point = event.position()  # logical widget coordinates, also under high-DPI scaling
        focus = click_to_source(point.x(), point.y(), self.width(), self.height(),
                                *self.source_size)
        if focus is not None:
            self.focus = focus
            self.selected.emit(*focus)
            self.update()


class IntroZoomDialog(QDialog):
    def __init__(self, parent=None, *, ffprobe_bin: str = "ffprobe",
                 ffmpeg_bin: str = "ffmpeg") -> None:
        super().__init__(parent)
        self.setWindowTitle("إضافة صورة افتتاحية")
        self.resize(980, 760)
        self.ffprobe_bin = ffprobe_bin
        self.ffmpeg_bin = ffmpeg_bin
        self.source: Image.Image | None = None
        self.image_path: Path | None = None
        self.audio_path: Path | None = None
        self.audio_duration: float | None = None
        self.config: IntroZoomConfig | None = None

        layout = QVBoxLayout(self)
        image_button = QPushButton("إضافة صورة افتتاحية")
        image_button.clicked.connect(self._choose_image)
        layout.addWidget(image_button)
        layout.addWidget(QLabel("اضغط على منتصف الدائرة المطلوبة"))
        self.selector = ImageSelector()
        self.selector.selected.connect(self._selected)
        layout.addWidget(self.selector, 1)
        self.selection_status = QLabel("اختر صورة ثم اضغط على الهدف")
        layout.addWidget(self.selection_status)

        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel("درجة التقريب"))
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(125, 800)
        self.zoom.setValue(250)
        self.zoom.valueChanged.connect(self._update_previews)
        zoom_row.addWidget(self.zoom, 1)
        self.zoom_label = QLabel("2.50×")
        zoom_row.addWidget(self.zoom_label)
        layout.addLayout(zoom_row)

        preview_row = QHBoxLayout()
        self.youtube_preview = QLabel("YouTube 16:9")
        self.reels_preview = QLabel("Reels 9:16")
        for label in (self.youtube_preview, self.reels_preview):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("background:#101318; border:1px solid #39414c")
            label.setMinimumHeight(190)
            preview_row.addWidget(label, 1)
        layout.addLayout(preview_row)

        audio_button = QPushButton("إضافة صوت افتتاحية")
        audio_button.clicked.connect(self._choose_audio)
        layout.addWidget(audio_button)
        self.audio_status = QLabel("اختر تسجيل صوتي لا يتجاوز 3 ثوانٍ")
        layout.addWidget(self.audio_status)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        layout.addWidget(self.buttons)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    def _choose_image(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "اختر صورة الافتتاحية", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not chosen:
            return
        try:
            image = open_image(Path(chosen))
        except ValueError as exc:
            QMessageBox.warning(self, "HEXA", str(exc))
            return
        if self.source is not None:
            self.source.close()
        self.source = image
        self.image_path = Path(chosen)
        self.selector.set_source(image)  # also invalidates the old selected circle
        self.selection_status.setText("اضغط على منتصف الدائرة المطلوبة")
        self._update_previews()
        self._update_ready()

    def _selected(self, x: float, y: float) -> None:
        self.selection_status.setText("تم حفظ موقع الأيقونة")
        self._update_previews()
        self._update_ready()

    def _choose_audio(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "اختر صوت الافتتاحية", "",
            "Audio (*.wav *.mp3 *.m4a *.aac *.flac *.ogg)")
        if not chosen:
            return
        try:
            duration = probe_voice(Path(chosen), self.ffprobe_bin, self.ffmpeg_bin)
        except ValueError as exc:
            QMessageBox.warning(self, "HEXA", str(exc))
            return
        self.audio_path = Path(chosen)
        self.audio_duration = duration
        self.audio_status.setText(f"تم حفظ صوت الافتتاحية ({duration:.2f} ثانية)")
        self._update_ready()

    def _update_previews(self) -> None:
        self.zoom_label.setText(f"{self.zoom.value() / 100:.2f}×")
        if self.source is None or self.selector.focus is None:
            for label in (self.youtube_preview, self.reels_preview):
                label.setPixmap(QPixmap())
            return
        config = IntroZoomConfig(
            self.image_path, self.audio_path or Path("voice.wav"),
            *self.selector.focus, self.zoom.value() / 100)
        prepared = PreparedIntro(config, self.source.width, self.source.height,
                                 self.audio_duration or 0, 75)
        for label, size in ((self.youtube_preview, (480, 270)),
                            (self.reels_preview, (270, 480))):
            frame = preview_frame(self.source, *size, prepared, final=True)
            pixmap = QPixmap.fromImage(_qimage(frame))
            frame.close()
            label.setPixmap(pixmap.scaled(
                label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def _update_ready(self) -> None:
        ready = (self.image_path is not None and self.selector.focus is not None
                 and self.audio_path is not None)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ready)

    def _accept(self) -> None:
        if not (self.image_path and self.audio_path and self.selector.focus):
            return
        self.config = IntroZoomConfig(self.image_path, self.audio_path,
                                      *self.selector.focus, self.zoom.value() / 100)
        self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.source is not None:
            self.source.close()
        super().closeEvent(event)
