from __future__ import annotations

import argparse
from pathlib import Path

from app.pipeline import StoryEnginePipeline


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="hexa", description="HEXA StoryEngine V2")
    commands = root.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate", help="Generate a video from Final Package + audio")
    generate.add_argument("--package", type=Path, required=True)
    generate.add_argument("--audio", type=Path, required=True)
    generate.add_argument(
        "--youtube-only",
        action="store_true",
        help="Legacy single 16:9 output into HEXA_OUTPUT_ROOT (default: YouTube + Reels bundle)",
    )
    generate.add_argument("--output-name", help="File name for --youtube-only output")

    serve = commands.add_parser("serve", help="Run the local Premiere engine API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--ssl-certfile")
    serve.add_argument("--ssl-keyfile")
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "generate":
        engine = StoryEnginePipeline()
        if args.youtube_only:
            output = engine.generate(
                package_path=args.package,
                audio_path=args.audio,
                output_name=args.output_name,
            )
            print(output)
            return 0
        if args.output_name:
            raise SystemExit("--output-name applies only to --youtube-only; bundles are versioned")
        bundle = engine.generate_bundle(package_path=args.package, audio_path=args.audio)
        for output in bundle.outputs.values():
            print(output.path)
        print(bundle.manifest_path)
        return 0

    if args.command == "serve":
        if args.host not in {"127.0.0.1", "localhost", "::1"}:
            raise SystemExit("HEXA local API may bind only to loopback")
        import uvicorn

        uvicorn.run(
            "app.api:app",
            host=args.host,
            port=args.port,
            workers=1,
            ssl_certfile=args.ssl_certfile,
            ssl_keyfile=args.ssl_keyfile,
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
