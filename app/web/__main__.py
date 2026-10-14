from __future__ import annotations

import os
import threading
import time
import urllib.request
import webbrowser

import uvicorn


def main() -> None:
    port = int(os.getenv("HEXA_WEB_PORT", "8787"))
    address = f"http://127.0.0.1:{port}"

    def open_when_ready() -> None:
        for _ in range(100):
            try:
                with urllib.request.urlopen(address + "/health", timeout=0.5):
                    webbrowser.open(address)
                    return
            except (OSError, TimeoutError):
                time.sleep(0.2)

    threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run("app.web.server:app", host="127.0.0.1", port=port, workers=1)


if __name__ == "__main__":
    main()
