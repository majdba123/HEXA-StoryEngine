from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.config import Settings
from app.diagnostics import BuildReportSession
from app.models import Stage
from app.pipeline import StoryEnginePipeline
from app.shared.errors import GenerationCancelledError


class GenerationWorker(QObject):
    progress = Signal(str, int, str)
    # bundle directory, YouTube output, Reels output
    finished = Signal(str, str, str)
    failed = Signal(str)
    cancelled = Signal()
    done = Signal()

    def __init__(
        self,
        *,
        settings: Settings,
        package_path: Path,
        audio_path: Path,
        report: BuildReportSession,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.package_path = package_path
        self.audio_path = audio_path
        self.report = report
        self.cancel_event = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            pipeline = StoryEnginePipeline(self.settings)
            bundle = pipeline.generate_bundle(
                package_path=self.package_path,
                audio_path=self.audio_path,
                job_id=self.report.job_id,
                progress=self._on_progress,
                cancelled=self.cancel_event.is_set,
            )
            for output in bundle.outputs.values():
                self.report.on_progress(Stage.final, 1.0, f"{output.target_id}: {output.path}")
            self.report.complete(bundle.youtube.path)
            self.finished.emit(
                str(bundle.directory),
                str(bundle.youtube.path),
                str(bundle.reels.path),
            )
        except GenerationCancelledError:
            self.report.cancel()
            self.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 - surfaced to UI and diagnostic report
            self.report.fail(exc)
            self.failed.emit(str(exc))
        finally:
            self.done.emit()

    def request_cancel(self) -> None:
        self.cancel_event.set()

    def _on_progress(self, stage: Stage, value: float, message: str) -> None:
        self.report.on_progress(stage, value, message)
        self.progress.emit(stage.value, round(value * 100), message)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"HEXA StoryEngine {__version__}")
        self.setMinimumSize(840, 620)
        self._thread: QThread | None = None
        self._worker: GenerationWorker | None = None
        self._report: BuildReportSession | None = None
        self._bundle_path: Path | None = None
        self._youtube_path: Path | None = None
        self._reels_path: Path | None = None

        settings = Settings.from_env()
        self.package_edit = QLineEdit()
        self.audio_edit = QLineEdit()
        self.export_root_edit = QLineEdit(
            str(settings.export_root) if settings.export_root is not None else "غير مضبوط"
        )
        self.export_root_edit.setReadOnly(True)
        for edit in (self.package_edit, self.audio_edit, self.export_root_edit):
            edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.status_label = QLabel("جاهز")
        self.status_label.setObjectName("status")
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)

        self.generate_button = QPushButton("توليد YouTube + Reels")
        self.cancel_button = QPushButton("إلغاء")
        self.report_button = QPushButton("استخراج تقرير التشخيص")
        self.open_youtube_button = QPushButton("فتح YouTube")
        self.open_reels_button = QPushButton("فتح Reels")
        self.open_folder_button = QPushButton("فتح مجلد النتيجة")
        self.open_export_root_button = QPushButton("فتح")
        self.open_log_button = QPushButton("فتح ملف السجل")
        self.clear_log_button = QPushButton("مسح اللوحة")

        self.cancel_button.setEnabled(False)
        self.report_button.setEnabled(False)
        self.open_youtube_button.setEnabled(False)
        self.open_reels_button.setEnabled(False)
        self.open_folder_button.setEnabled(False)
        self.open_log_button.setEnabled(False)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("HEXA StoryEngine")
        title.setObjectName("title")
        subtitle = QLabel("اختر الـ Final Package والصوت، ثم ولّد الفيديو.")
        subtitle.setObjectName("subtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        root.addLayout(self._package_row())
        root.addLayout(self._file_row("الصوت", self.audio_edit, self._browse_audio))
        root.addLayout(self._export_root_row())

        actions = QHBoxLayout()
        actions.addWidget(self.generate_button)
        actions.addWidget(self.cancel_button)
        root.addLayout(actions)

        root.addWidget(self.progress_bar)
        root.addWidget(self.status_label)

        log_box = QGroupBox("لوحة السجل")
        log_layout = QVBoxLayout(log_box)
        log_layout.addWidget(self.log_view, 1)
        log_actions = QHBoxLayout()
        log_actions.addWidget(self.open_log_button)
        log_actions.addWidget(self.clear_log_button)
        log_actions.addStretch(1)
        log_layout.addLayout(log_actions)
        root.addWidget(log_box, 1)

        result_actions = QHBoxLayout()
        result_actions.addWidget(self.open_youtube_button)
        result_actions.addWidget(self.open_reels_button)
        result_actions.addWidget(self.open_folder_button)
        result_actions.addWidget(self.report_button)
        root.addLayout(result_actions)

        self.setCentralWidget(central)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._apply_style()

        self.generate_button.clicked.connect(self._start_generation)
        self.cancel_button.clicked.connect(self._cancel_generation)
        self.report_button.clicked.connect(self._export_report)
        self.open_youtube_button.clicked.connect(self._open_youtube)
        self.open_reels_button.clicked.connect(self._open_reels)
        self.open_folder_button.clicked.connect(self._open_folder)
        self.open_export_root_button.clicked.connect(self._open_export_root)
        self.open_log_button.clicked.connect(self._open_log)
        self.clear_log_button.clicked.connect(self.log_view.clear)

    def _package_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        label = QLabel("Final Package")
        zip_button = QPushButton("اختيار ZIP")
        folder_button = QPushButton("اختيار مجلد")
        zip_button.clicked.connect(self._browse_package_zip)
        folder_button.clicked.connect(self._browse_package_folder)
        row.addWidget(label)
        row.addWidget(self.package_edit, 1)
        row.addWidget(zip_button)
        row.addWidget(folder_button)
        return row

    def _file_row(self, label_text: str, edit: QLineEdit, callback) -> QHBoxLayout:
        row = QHBoxLayout()
        label = QLabel(label_text)
        button = QPushButton("اختيار")
        button.clicked.connect(callback)
        row.addWidget(label)
        row.addWidget(edit, 1)
        row.addWidget(button)
        return row

    def _export_root_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        label = QLabel("مجلد التصدير")
        row.addWidget(label)
        row.addWidget(self.export_root_edit, 1)
        row.addWidget(self.open_export_root_button)
        return row

    def _browse_package_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "اختر Final Package", "", "ZIP (*.zip)")
        if path:
            self.package_edit.setText(path)

    def _browse_package_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "اختر مجلد Final Package")
        if path:
            self.package_edit.setText(path)

    def _browse_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "اختر ملف الصوت",
            "",
            "Audio (*.wav *.mp3 *.m4a *.aac *.flac *.ogg);;All Files (*)",
        )
        if path:
            self.audio_edit.setText(path)

    @Slot()
    def _start_generation(self) -> None:
        package = Path(self.package_edit.text().strip()).expanduser()
        audio = Path(self.audio_edit.text().strip()).expanduser()
        settings = Settings.from_env()
        self._refresh_export_root(settings)

        if not package.exists():
            QMessageBox.warning(self, "HEXA", "اختر Final Package صالح.")
            return
        if not audio.is_file():
            QMessageBox.warning(self, "HEXA", "اختر ملف صوت صالح.")
            return
        if settings.export_root is None:
            QMessageBox.warning(
                self,
                "HEXA",
                "مجلد التصدير غير مضبوط.\n"
                "اضبط export_root في hexa.settings.json أو HEXA_EXPORT_ROOT ثم أعد المحاولة.",
            )
            return
        job_id = uuid.uuid4().hex
        report = BuildReportSession(
            job_id=job_id,
            settings=settings,
            package_path=package,
            audio_path=audio,
        )
        worker = GenerationWorker(
            settings=settings,
            package_path=package.resolve(),
            audio_path=audio.resolve(),
            report=report,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._thread_finished)

        self._thread = thread
        self._worker = worker
        self._report = report
        self._bundle_path = None
        self._youtube_path = None
        self._reels_path = None
        self.log_view.clear()
        self.progress_bar.setValue(0)
        self.status_label.setText("بدء المعالجة...")
        self.generate_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.report_button.setEnabled(False)
        self.open_youtube_button.setEnabled(False)
        self.open_reels_button.setEnabled(False)
        self.open_folder_button.setEnabled(False)
        self.open_log_button.setEnabled(True)
        self.log_view.append(f"LOG: {report.log_path}")
        thread.start()

    @Slot(str, int, str)
    def _on_progress(self, stage: str, percent: int, message: str) -> None:
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)
        self.log_view.append(f"[{percent:>3}%] {stage}: {message}")

    @Slot(str, str, str)
    def _on_finished(self, bundle_path: str, youtube_path: str, reels_path: str) -> None:
        self._bundle_path = Path(bundle_path)
        self._youtube_path = Path(youtube_path)
        self._reels_path = Path(reels_path)
        self.progress_bar.setValue(100)
        self.status_label.setText("تم توليد نسختي YouTube وReels بنجاح")
        self.log_view.append(f"DONE YOUTUBE: {youtube_path}")
        self.log_view.append(f"DONE REELS: {reels_path}")
        self.log_view.append(f"BUNDLE: {bundle_path}")
        self.open_youtube_button.setEnabled(True)
        self.open_reels_button.setEnabled(True)
        self.open_folder_button.setEnabled(True)
        self.report_button.setEnabled(True)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self.status_label.setText("فشل التوليد — استخرج تقرير التشخيص")
        self.log_view.append(f"ERROR: {message}")
        self.report_button.setEnabled(True)
        QMessageBox.critical(
            self,
            "HEXA",
            "حدثت مشكلة أثناء التوليد.\nاستخرج تقرير التشخيص وأرسله لفحص السبب.",
        )

    @Slot()
    def _on_cancelled(self) -> None:
        self.status_label.setText("تم إلغاء العملية")
        self.log_view.append("CANCELLED")
        self.report_button.setEnabled(True)

    @Slot()
    def _thread_finished(self) -> None:
        self.generate_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self._thread = None
        self._worker = None

    @Slot()
    def _cancel_generation(self) -> None:
        if self._worker:
            self._worker.request_cancel()
            self.cancel_button.setEnabled(False)
            self.status_label.setText("تم طلب الإلغاء — سيتم الإيقاف عند أول نقطة آمنة")

    @Slot()
    def _export_report(self) -> None:
        if self._report is None:
            return
        default_name = f"HEXA-diagnostic-{self._report.job_id[:8]}.zip"
        settings = Settings.from_env()
        initial_dir = self._bundle_path or settings.export_root or settings.output_root
        initial = initial_dir / default_name
        path, _ = QFileDialog.getSaveFileName(
            self,
            "حفظ تقرير التشخيص",
            str(initial),
            "ZIP (*.zip)",
        )
        if not path:
            return
        try:
            exported = self._report.export_zip(Path(path))
        except Exception as exc:  # noqa: BLE001 - diagnostic export must surface failures
            QMessageBox.critical(self, "HEXA", f"تعذر إنشاء التقرير:\n{exc}")
            return
        self.log_view.append(f"REPORT: {exported}")
        QMessageBox.information(self, "HEXA", f"تم حفظ التقرير:\n{exported}")

    @Slot()
    def _open_youtube(self) -> None:
        if self._youtube_path and self._youtube_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._youtube_path)))

    @Slot()
    def _open_reels(self) -> None:
        if self._reels_path and self._reels_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._reels_path)))

    @Slot()
    def _open_folder(self) -> None:
        if self._bundle_path and self._bundle_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._bundle_path)))

    @Slot()
    def _open_export_root(self) -> None:
        settings = Settings.from_env()
        self._refresh_export_root(settings)
        if settings.export_root is None:
            QMessageBox.warning(self, "HEXA", "مجلد التصدير غير مضبوط.")
            return
        target = settings.export_root.expanduser()
        if not target.exists():
            QMessageBox.information(
                self,
                "HEXA",
                "مجلد التصدير لم يُنشأ بعد. سيتم إنشاؤه عند أول توليد ناجح.",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.resolve())))

    def _refresh_export_root(self, settings: Settings) -> None:
        self.export_root_edit.setText(
            str(settings.export_root) if settings.export_root is not None else "غير مضبوط"
        )

    @Slot()
    def _open_log(self) -> None:
        if self._report is None:
            return
        path = self._report.log_path
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        elif path.parent.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #121417; color: #f2f3f5; font-size: 14px; }
            QLabel#title { font-size: 28px; font-weight: 700; }
            QLabel#subtitle { color: #aeb4bd; margin-bottom: 8px; }
            QLabel#status { color: #cbd2db; padding: 4px 0; }
            QGroupBox {
                border: 1px solid #323842; border-radius: 8px; margin-top: 10px;
                padding-top: 10px; font-weight: 600;
            }
            QGroupBox::title { subcontrol-origin: margin; right: 10px; padding: 0 6px; }
            QLineEdit, QTextEdit {
                background: #1b1f24; border: 1px solid #323842; border-radius: 7px;
                padding: 8px; color: #f7f7f7;
            }
            QPushButton {
                background: #242a31; border: 1px solid #39414c; border-radius: 7px;
                padding: 9px 14px; min-height: 20px;
            }
            QPushButton:hover { background: #2c333c; }
            QPushButton:disabled { color: #737a84; background: #191d22; }
            QProgressBar {
                border: 1px solid #323842; border-radius: 7px; text-align: center;
                background: #1b1f24; min-height: 20px;
            }
            QProgressBar::chunk { background: #4f8cff; border-radius: 6px; }
            """
        )


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("HEXA StoryEngine")
    app.setApplicationVersion(__version__)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
