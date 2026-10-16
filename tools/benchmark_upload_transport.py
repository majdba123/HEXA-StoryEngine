"""Disposable upload transport benchmark; never point at a production endpoint."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


def fingerprint(path: Path, chunk: int) -> str:
    outer = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(chunk):
            outer.update(hashlib.sha256(block).hexdigest().encode())
    return outer.hexdigest()


def upload(client: httpx.Client, base: str, path: Path, chunk: int, protocol: int, rtt: float, uploads_root: Path):
    audio = b"benchmark-audio"
    prep_start = time.perf_counter()
    files = [
        {"id": "p0", "path": "package.zip", "size": path.stat().st_size,
         "fingerprint": fingerprint(path, chunk), "role": "package"},
        {"id": "audio", "path": "voice.wav", "size": len(audio),
         "fingerprint": hashlib.sha256(hashlib.sha256(audio).hexdigest().encode()).hexdigest(),
         "role": "audio"},
    ]
    preparation = time.perf_counter() - prep_start
    manifest = {"mode": "zip", "files": files, "chunk_size": chunk}
    if protocol == 2:
        manifest["protocol"] = 2
    requests = 0
    timings = []

    def call(method, url, **kwargs):
        nonlocal requests
        if rtt:
            time.sleep(rtt)
        start = time.perf_counter()
        response = client.request(method, base + url, **kwargs)
        timings.append(time.perf_counter() - start + rtt)
        requests += 1
        response.raise_for_status()
        return response

    start = time.perf_counter()
    init_start = time.perf_counter()
    state = call("POST", "/api/uploads", json={"key": secrets.token_hex(16), "manifest": manifest}).json()
    initialization = time.perf_counter() - init_start
    transfer_start = time.perf_counter()
    for fid, source in (("p0", path), ("audio", audio)):
        stream = source.open("rb") if isinstance(source, Path) else None
        try:
            index = 0
            while True:
                block = stream.read(chunk) if stream else (source if index == 0 else b"")
                if not block:
                    break
                state = call("PUT", f"/api/uploads/{state['id']}/files/{fid}/chunks/{index}",
                             content=block, headers={"X-Chunk-SHA256": hashlib.sha256(block).hexdigest()}).json()
                if protocol == 1:
                    state = call("GET", f"/api/uploads/{state['id']}").json()
                index += 1
        finally:
            if stream:
                stream.close()
    transfer = time.perf_counter() - transfer_start
    assert state["files"]["p0"] == path.stat().st_size
    assert state["files"]["audio"] == len(audio)
    elapsed = time.perf_counter() - start
    stored = uploads_root / state["id"] / "p0"
    with path.open("rb") as source, stored.open("rb") as received:
        assert hashlib.file_digest(source, "sha256").hexdigest() == hashlib.file_digest(received, "sha256").hexdigest()
    assert (uploads_root / state["id"] / "audio").read_bytes() == audio
    return {"protocol": protocol, "size_mib": path.stat().st_size / 1048576,
            "simulated_rtt_ms": rtt * 1000, "preparation_s": preparation,
            "initialization_s": initialization, "transfer_s": transfer,
            "total_to_durable_upload_s": preparation + elapsed,
            "mib_per_s": (path.stat().st_size / 1048576) / elapsed,
            "requests": requests, "retries": 0,
            "median_request_ms": statistics.median(timings) * 1000,
            "p95_request_ms": sorted(timings)[int(.95 * (len(timings) - 1))] * 1000,
            "finalization_s": None, "job_admission_s": None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--size-mib", type=int, nargs="+", default=[1, 44, 100, 250])
    parser.add_argument("--rtt-ms", type=int, nargs="+", default=[0, 50, 150])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix="hexa-upload-bench-", ignore_cleanup_errors=True) as temp:
        root = Path(temp)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        env = {**os.environ, "PYTHONPATH": str(args.source.resolve()),
               "HEXA_WEB_STORAGE": str(root / "storage"),
               "HEXA_WEB_UPLOAD_ROOT": str(root / "uploads"),
               "HEXA_WEB_V2_ENABLED": "1",
               "HEXA_ADMIN_EMAIL": "benchmark@local.invalid",
               "HEXA_ADMIN_BOOTSTRAP_PASSWORD": secrets.token_urlsafe(32)}
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.web.server:create_app",
                                   "--factory", "--host", "127.0.0.1", "--port", str(port)],
                                  cwd=args.source, env=env, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.PIPE)
        base = f"http://127.0.0.1:{port}"
        try:
            with httpx.Client(timeout=120) as client:
                for _ in range(100):
                    try:
                        if client.get(base + "/health").status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError("Local benchmark server did not start")
                login = client.post(base + "/api/session", json={"email": env["HEXA_ADMIN_EMAIL"],
                    "password": env["HEXA_ADMIN_BOOTSTRAP_PASSWORD"]})
                login.raise_for_status()
                client.headers["X-CSRF-Token"] = login.json()["csrf"]
                for size in args.size_mib:
                    path = root / f"{size}.bin"
                    with path.open("wb") as output:
                        block = bytes(range(256)) * 4096
                        for _ in range(size):
                            output.write(block)
                    for rtt_ms in args.rtt_ms:
                        protocol = 2 if args.source.resolve() == Path(__file__).resolve().parents[1] else 1
                        chunk = 4 * 1048576 if protocol == 2 else 256 * 1024
                        results.append(upload(client, base, path, chunk, protocol, rtt_ms / 1000, root / "uploads"))
                        print(json.dumps(results[-1]), flush=True)
                    path.unlink()
        finally:
            server.terminate()
            try:
                server.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.communicate(timeout=10)
            time.sleep(1)  # Windows may release SQLite handles just after process exit.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"environment": "localhost HTTP; application sleep approximates RTT, no network shaping",
                                           "results": results}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
