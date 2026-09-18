from __future__ import annotations

import argparse
import base64
import io
import tarfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore the frozen HEXA V7 acceptance runtime sources.")
    parser.add_argument("destination", type=Path, nargs="?", default=Path("v7_runtime"))
    args = parser.parse_args()
    checkpoint = Path(__file__).resolve().parent
    payload = base64.b64decode((checkpoint / "runtime_source.tar.gz.b64").read_text(encoding="ascii"))
    args.destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        archive.extractall(args.destination)
    print(args.destination.resolve())


if __name__ == "__main__":
    main()
