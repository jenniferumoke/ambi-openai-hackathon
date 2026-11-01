"""Start the local profile lab dashboard."""

import argparse

from dotenv import load_dotenv
import uvicorn

from bench.paths import ROOT
from bench.server import create_app


def main():
    parser = argparse.ArgumentParser(description="AMBI-Bench: simple profile lab")
    parser.add_argument(
        "--serve", action="store_true", help="Start the dashboard (default)"
    )
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    print(f"AMBI-Bench: http://127.0.0.1:{args.port} (no sensors started)", flush=True)
    uvicorn.run(
        create_app(port=args.port),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        timeout_graceful_shutdown=2,
    )


if __name__ == "__main__":
    main()
