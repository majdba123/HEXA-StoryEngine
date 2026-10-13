"""Desktop pre-render check of the configured production export root (no Qt dependency).

The GUI no longer asks for an export folder: the destination comes from configuration
(`HEXA_EXPORT_ROOT`, then `export_root` in hexa.settings.json). Before any work starts the
desktop runs the pipeline's own `ExportRoot.validate()` so a missing, unwritable or full
drive is reported clearly up front. Nothing falls back to another drive; the pipeline still
validates again as its first step.
"""
from __future__ import annotations

from app.config import Settings
from app.final.bundle import ExportRoot
from app.shared.errors import StageFailedError

NOT_CONFIGURED = (
    "مجلد التصدير غير مضبوط.\n"
    "اضبط export_root في hexa.settings.json أو HEXA_EXPORT_ROOT ثم أعد المحاولة."
)


def export_root_problem(settings: Settings) -> str | None:
    """Return a user-facing Arabic error, or None when the export root is usable."""
    if settings.export_root is None:
        return NOT_CONFIGURED
    try:
        ExportRoot(settings.export_root, min_free_bytes=settings.export_min_free_bytes).validate()
    except StageFailedError as exc:
        details = exc.details or {}
        path = details.get("path") or str(settings.export_root)
        if details.get("code") == "EXPORT_ROOT_INSUFFICIENT_SPACE":
            free = int(details.get("free_bytes", 0)) / 1024 ** 3
            need = int(details.get("required_bytes", 0)) / 1024 ** 3
            return (f"لا توجد مساحة كافية في مجلد التصدير:\n{path}\n"
                    f"المتاح {free:.1f} GB والمطلوب {need:.1f} GB على الأقل.")
        reason = {
            "export drive is not available": "القرص غير موجود أو غير متصل.",
            "export root cannot be created": "تعذر إنشاء المجلد.",
            "export root is not writable": "لا توجد صلاحية كتابة في المجلد.",
            "export root must not be a symlink or junction": "المجلد اختصار (symlink/junction) وهذا غير مسموح.",
            "export root must be an absolute path": "المسار يجب أن يكون كاملًا (مثل E:\\HEXA_Exports).",
        }.get(str(exc), str(exc))
        return f"تعذر استخدام مجلد التصدير:\n{path}\n{reason}\nلم يبدأ التوليد."
    return None
