import argparse
import asyncio
import json

from dotenv import load_dotenv

from bench.runner import BenchRunner, ROOT, RunConfig


async def run_once(args):
    runner = BenchRunner()
    runner.start(RunConfig(mode=args.mode, adapter=args.adapter, split=args.split))
    await runner.task
    result = runner.current
    print(json.dumps({"status": result["status"], "report": str(runner.output_dir / f"{result['id']}.json"),
                      "metrics": result["metrics"]}, indent=2))
    return 0 if result["status"] == "completed" and not (result["metrics"]["overall"]["failed"] or result["metrics"]["overall"]["errors"]) else 1


def main():
    parser = argparse.ArgumentParser(description="AMBI-Bench: real policy checks, optional live classifier runs, workspace lab")
    parser.add_argument("--serve", action="store_true", help="Start the local live dashboard")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--adapter", choices=["product", "always_quiet", "always_intervene"], default="product")
    parser.add_argument("--split", choices=["all", "dev", "holdout"], default="all")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    if args.serve:
        import uvicorn
        from bench.server import create_app
        print(f"AMBI-Bench: http://127.0.0.1:{args.port} (no sensors or desktop actions started)", flush=True)
        uvicorn.run(create_app(port=args.port), host="127.0.0.1", port=args.port, access_log=False)
        return 0
    return asyncio.run(run_once(args))


if __name__ == "__main__":
    raise SystemExit(main())
