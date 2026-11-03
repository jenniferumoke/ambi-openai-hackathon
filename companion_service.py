"""Sensor-idle production service entry point for packaged Mac/Windows hosts."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, choices=(8765, 8767), default=8765)
    args = parser.parse_args()
    if 'AMBI_DATA_DIR' not in os.environ:
        base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'Library/Application Support')))
        os.environ['AMBI_DATA_DIR'] = str(base / 'Ambi' / 'data')
    data = Path(os.environ['AMBI_DATA_DIR'])
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.environ['AMBI_FRONTEND_ORIGINS'] = f'http://127.0.0.1:{args.port},http://localhost:{args.port}'
    if not getattr(sys, "frozen", False) and os.environ.get('AMBI_NATIVE_HOST') != '1':
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent / ".env")
    from agents import set_tracing_disabled
    import uvicorn
    from server import create_app
    set_tracing_disabled(True)
    uvicorn.run(create_app(seed=False, auto_start=False), host='127.0.0.1', port=args.port, access_log=False)


if __name__ == '__main__':
    main()
