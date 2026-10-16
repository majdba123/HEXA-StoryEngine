"""Disposable Firefox V2 refresh/reselection smoke test on localhost."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import httpx
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options


def wait_for(check, seconds=60):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            result = check()
        except (httpx.ConnectError, sqlite3.OperationalError):
            result = None
        if result:
            return result
        time.sleep(.1)
    raise TimeoutError("Browser upload checkpoint not reached")


def checkpoint(db_path: Path):
    if not db_path.exists():
        return None
    with sqlite3.connect(db_path, timeout=2) as db:
        row = db.execute("SELECT u.id,u.state,f.offset FROM uploads u JOIN upload_files f ON f.upload_id=u.id WHERE f.file_id='p0' ORDER BY u.created DESC LIMIT 1").fetchone()
    return row


def main():
    with tempfile.TemporaryDirectory(prefix="hexa-firefox-upload-", ignore_cleanup_errors=True) as temp:
        root = Path(temp)
        package = root / "browser-package.zip"
        block = bytes(range(256)) * 4096
        with package.open("wb") as stream:
            for _ in range(100):
                stream.write(block)
        audio = root / "voice.wav"
        with wave.open(str(audio), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"\0\0" * 32000)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        source = Path(__file__).resolve().parents[1]
        export = root / "exports"
        export.mkdir()
        env = {**os.environ, "PYTHONPATH": str(source),
               "HEXA_WEB_STORAGE": str(root / "storage"),
               "HEXA_WEB_UPLOAD_ROOT": str(root / "uploads"),
               "HEXA_WORK_ROOT": str(root / "work"),
               "HEXA_EXPORT_ROOT": str(export),
               "HEXA_WEB_V2_ENABLED": "1",
               "HEXA_ADMIN_EMAIL": "browser@local.invalid",
               "HEXA_ADMIN_BOOTSTRAP_PASSWORD": secrets.token_urlsafe(32)}
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.web.server:create_app", "--factory",
                                   "--host", "127.0.0.1", "--port", str(port)], cwd=source, env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        browser = None
        base = f"http://127.0.0.1:{port}"
        try:
            with httpx.Client() as probe:
                wait_for(lambda: probe.get(base + "/health").status_code == 200 if server.poll() is None else False, 20)
            options = Options()
            options.add_argument("-headless")
            browser = webdriver.Firefox(options=options)
            browser.get(base + "/login")
            browser.find_element(By.ID, "email").send_keys(env["HEXA_ADMIN_EMAIL"])
            browser.find_element(By.ID, "password").send_keys(env["HEXA_ADMIN_BOOTSTRAP_PASSWORD"])
            browser.find_element(By.CSS_SELECTOR, "#login button").click()
            wait_for(lambda: browser.find_elements(By.ID, "package"), 20)
            browser.find_element(By.ID, "package").send_keys(str(package))
            browser.find_element(By.ID, "audio").send_keys(str(audio))
            browser.find_element(By.ID, "generate").click()
            db_path = root / "storage" / "jobs.sqlite3"
            try:
                first = wait_for(lambda: (r if r and 0 < r[2] < package.stat().st_size else None) if (r := checkpoint(db_path)) else None, 20)
            except TimeoutError:
                print(json.dumps({"url": browser.current_url,
                                  "status": browser.find_element(By.ID, "status").text,
                                  "checkpoint": checkpoint(db_path)}), flush=True)
                raise
            upload_id = first[0]
            browser.refresh()
            wait_for(lambda: browser.find_elements(By.ID, "package"), 20)
            wait_for(lambda: browser.find_element(By.ID, "generate").is_enabled(), 30)
            browser.find_element(By.ID, "package").send_keys(str(package))
            browser.find_element(By.ID, "audio").send_keys(str(audio))
            browser.find_element(By.ID, "generate").click()
            try:
                final = wait_for(lambda: (r if r and r[2] == package.stat().st_size else None) if (r := checkpoint(db_path)) else None, 45)
            except TimeoutError:
                print(json.dumps({"url": browser.current_url,
                                  "status": browser.find_element(By.ID, "status").text,
                                  "checkpoint": checkpoint(db_path),
                                  "generate_disabled": browser.find_element(By.ID, "generate").get_attribute("disabled"),
                                  "js": browser.execute_script("return {files: files.map(f => [f.id, f.file.size]), uploadBusy, preparing, stopped, uploadKey, saved: localStorage.getItem(uploadKey)}")}), flush=True)
                raise
            with (root / "uploads" / upload_id / "p0").open("rb") as stream, package.open("rb") as original:
                assert hashlib.file_digest(stream, "sha256").hexdigest() == hashlib.file_digest(original, "sha256").hexdigest()
            with sqlite3.connect(db_path) as db:
                assert db.execute("SELECT COUNT(*) FROM uploads").fetchone()[0] == 1
            assert final[0] == upload_id
            print(json.dumps({"browser": "Firefox headless", "size_bytes": package.stat().st_size,
                              "upload_id": upload_id, "committed_before_refresh": first[2],
                              "committed_after_reselection": final[2], "sha256_equal": True,
                              "upload_state": final[1]}))
        finally:
            if browser:
                browser.quit()
            server.terminate()
            try:
                server.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.communicate(timeout=10)
            time.sleep(1)


if __name__ == "__main__":
    main()
