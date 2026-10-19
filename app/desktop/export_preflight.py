"""Desktop pre-render check of the configured production export root (no Qt dependency).

The GUI no longer asks for an export folder: the destination comes from configuration
(`HEXA_EXPORT_ROOT`, then `export_root` in hexa.settings.json). Before any work starts the
desktop runs the pipeline's own `ExportRoot.validate()` so a missing, unwritable or full
drive is reported clearly up front. Nothing falls back to another drive; the pipeline still
validates again as its first step.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from app.config import LOCAL_SETTINGS_FILE, Settings
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


def initialize_windows_export_root(
    *,
    platform: str | None = None,
    drive_root: Path | None = None,
    settings_file: Path | None = None,
) -> str | None:
    """One-time, desktop-only setup for Windows users saving results on E:.

    Save the chosen location in the ignored machine-local settings, never in the
    repository and never as an implicit pipeline fallback. Explicit environment
    variables and configured paths always win. Missing E: fails visibly; do not
    quietly export to C: or create a bogus relative Windows path on non-Windows.
    """
    if (platform or os.name) != "nt":
        return None
    if os.getenv("HEXA_EXPORT_ROOT") or os.getenv("HEXA_SETTINGS_FILE"):
        return None

    path = settings_file or LOCAL_SETTINGS_FILE
    drive = drive_root or Path("E:/")
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return f"إعدادات HEXA غير صالحة:\n{path}\nيجب أن يكون الملف كائن JSON."
        else:
            payload = {}
    except (OSError, ValueError) as exc:
        return f"تعذر قراءة إعدادات HEXA:\n{path}\n{exc}"

    if payload.get("export_root"):
        return None
    if not drive.is_dir():
        return ("قرص E: غير موجود أو غير متصل.\n"
                "وصل القرص ثم أعد المحاولة. لن يتم حفظ النتائج على C: تلقائيًا.")

    destination = drive / "HEXA_Exports"
    updated = {**payload, "export_root": str(destination)}
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        return f"تعذر حفظ إعداد مجلد التصدير:\n{path}\n{exc}"
    finally:
        temporary.unlink(missing_ok=True)
    return None
