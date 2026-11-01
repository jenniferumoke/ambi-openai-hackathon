"""Launch unchanged AMBI with a fresh demo memory database, never normal user memory."""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from agents import set_tracing_disabled
import uvicorn

from bench.profile_lab import ProfileLab
from bench.runner import ROOT
from server import create_app


def main():
    parser = argparse.ArgumentParser(
        description="Start AMBI with an isolated fictional profile"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--session", help="Prepared session ID from AMBI-Bench")
    group.add_argument(
        "--profile",
        choices=["rowan", "ellis", "nora"],
        help="Prepare a fresh profile on this machine",
    )
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    set_tracing_disabled(True)
    lab = ProfileLab(
        Path(os.getenv("AMBI_BENCH_PROFILE_ROOT", str(ROOT / "data/bench/profiles")))
    )
    item = lab.prepare(args.profile) if args.profile else lab.load(args.session)
    if not (ROOT / "ui/dist/index.html").is_file():
        raise SystemExit("Build the UI first: cd ui && npm ci && npm run build")
    print(
        f"Demo profile: {item['profile']['name']}. Isolated memory loaded. Open http://127.0.0.1:8765 and click Start session when ready.",
        flush=True,
    )
    uvicorn.run(
        create_app(db_path=Path(item["path"]) / "memory.sqlite3", seed=False),
        host="127.0.0.1",
        port=8765,
        access_log=False,
        timeout_graceful_shutdown=2,
    )


if __name__ == "__main__":
    main()
