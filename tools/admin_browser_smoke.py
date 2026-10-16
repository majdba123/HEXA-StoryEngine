"""Disposable Windows Edge smoke test for the local account/admin UI.

Install playwright in the local venv first. No browser binary is downloaded: the
script uses installed Microsoft Edge and leaves only screenshots in .hexa.
"""
from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.final.bundle import ExportBundleWriter


ROOT = Path(__file__).resolve().parents[1]
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> None:
    if not EDGE.is_file():
        raise SystemExit("Installed Microsoft Edge is required for this Windows browser test")
    artifacts = ROOT / ".hexa" / "admin-browser-artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    admin_password = secrets.token_urlsafe(24)
    user_password = secrets.token_urlsafe(24)
    new_password = secrets.token_urlsafe(24)
    with tempfile.TemporaryDirectory(dir=ROOT / ".hexa", prefix="admin-browser-", ignore_cleanup_errors=True) as data:
        local = Path(data)
        env = os.environ.copy()
        env.update({
            "HEXA_WEB_STORAGE": str(local / "web"),
            "HEXA_WEB_UPLOAD_ROOT": str(local / "uploads"),
            "HEXA_WORK_ROOT": str(local / "work"),
            "HEXA_OUTPUT_ROOT": str(local / "outputs"),
            "HEXA_EXPORT_ROOT": str(local / "exports"),
            "HEXA_ADMIN_EMAIL": "browser-admin@example.invalid",
            "HEXA_ADMIN_BOOTSTRAP_PASSWORD": admin_password,
        })
        exports = local / "exports"
        exports.mkdir()
        writer = ExportBundleWriter(exports)
        bundle = writer.reserve("BROWSER_TEST")
        for suffix, size in (("YOUTUBE", "64x36"), ("REELS", "36x64")):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            f"color=c=navy:s={size}:r=10:d=0.4", "-an", "-pix_fmt", "yuv420p",
                            "-threads", "1", str(bundle.output_path(suffix))], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        encoded_bytes = sum(bundle.output_path(suffix).stat().st_size for suffix in ("YOUTUBE", "REELS"))
        writer.publish(bundle, {"completed": True, "export_identity": bundle.slug,
                                "export_version": bundle.version,
                                "generated_at": datetime.now(timezone.utc).isoformat(),
                                "outputs": {"YOUTUBE_16_9": {"filename": bundle.output_path("YOUTUBE").name},
                                            "REELS_9_16": {"filename": bundle.output_path("REELS").name}}})
        bundle_bytes = sum(path.stat().st_size for path in bundle.directory.iterdir() if path.is_file())
        port = free_port()
        url = f"http://127.0.0.1:{port}"
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.web.server:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        try:
            for _ in range(100):
                if proc.poll() is not None:
                    raise RuntimeError("Local server stopped before browser test")
                try:
                    with urllib.request.urlopen(f"{url}/health", timeout=0.3):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Local server did not start")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=str(EDGE), headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.goto(f"{url}/login")
                page.get_by_label("البريد الإلكتروني").fill("browser-admin@example.invalid")
                page.get_by_label("كلمة المرور").fill(admin_password)
                page.get_by_role("button", name="دخول").click()
                page.wait_for_url(url + "/")
                assert page.get_by_role("link", name="Admin Dashboard").is_visible()
                page.get_by_role("link", name="Admin Dashboard").click()
                page.wait_for_url(url + "/admin")
                assert page.get_by_text("لوحة إدارة HEXA").is_visible()
                page.screenshot(path=str(artifacts / "admin-desktop.png"), full_page=True)
                page.on("dialog", lambda dialog: dialog.accept())
                page.get_by_role("button", name="إدارة الفيديو").click()
                page.get_by_text("BROWSER_TEST", exact=True).wait_for()
                page.get_by_role("button", name="حذف النسخة").click()
                page.get_by_text("DELETED", exact=True).wait_for()
                assert not bundle.directory.exists()
                page.get_by_role("button", name="إدارة المستخدمين").click()
                page.locator('input[name="email"]').fill("browser-user@example.invalid")
                page.locator('input[name="password"]').fill(user_password)
                page.get_by_role("button", name="إضافة مستخدم").click()
                page.get_by_text("browser-user@example.invalid").wait_for()
                page.get_by_role("button", name="تسجيل الخروج").click()
                page.wait_for_url(url + "/login")
                page.get_by_label("البريد الإلكتروني").fill("browser-user@example.invalid")
                page.get_by_label("كلمة المرور").fill(user_password)
                page.get_by_role("button", name="دخول").click()
                page.wait_for_url(url + "/change-password")
                page.get_by_label("كلمة المرور الحالية").fill(user_password)
                page.get_by_label("كلمة المرور الجديدة").fill(new_password)
                page.get_by_role("button", name="حفظ").click()
                page.wait_for_url(url + "/login")
                page.get_by_label("البريد الإلكتروني").fill("browser-user@example.invalid")
                page.get_by_label("كلمة المرور").fill(new_password)
                page.get_by_role("button", name="دخول").click()
                page.wait_for_url(url + "/")
                assert page.get_by_role("link", name="Admin Dashboard").is_hidden()
                assert page.locator("#package").count() == 1
                assert page.locator("#audio").count() == 1
                assert page.locator("#folder").count() == 0
                assert page.locator("#export-path").count() == 0
                page.set_viewport_size({"width": 390, "height": 844})
                page.screenshot(path=str(artifacts / "user-mobile.png"), full_page=True)
                page.get_by_role("button", name="تسجيل الخروج").click()
                page.wait_for_url(url + "/login")
                page.get_by_label("البريد الإلكتروني").fill("browser-admin@example.invalid")
                page.get_by_label("كلمة المرور").fill(admin_password)
                page.get_by_role("button", name="دخول").click()
                page.wait_for_url(url + "/")
                page.get_by_role("link", name="Admin Dashboard").click()
                page.get_by_role("button", name="إدارة المستخدمين").click()
                row = page.locator("#user-rows tr").filter(has_text="browser-user@example.invalid")
                row.wait_for()
                row.get_by_role("button", name="تعطيل").click()
                row.get_by_text("معطل", exact=True).wait_for()
                row.get_by_role("button", name="تفعيل").click()
                row.get_by_text("نشط", exact=True).wait_for()
                row.get_by_role("button", name="حذف", exact=True).click()
                row.get_by_text("محذوف", exact=True).wait_for()
                browser.close()
            print(f"PASS browser admin/user lifecycle, export deletion ({bundle_bytes} bundle bytes, {encoded_bytes} encoded bytes), responsive screenshots")
        finally:
            proc.terminate()
            proc.wait(timeout=15)


if __name__ == "__main__":
    main()
