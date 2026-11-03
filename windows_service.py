"""Windows companion service; separate loopback port, explicit sensor startup."""
from pathlib import Path
import os

PORT = 8767
ROOT = Path(__file__).resolve().parent


def create_windows_app():
    from dotenv import load_dotenv
    from agents import set_tracing_disabled
    from server import create_app
    load_dotenv(ROOT / '.env')
    set_tracing_disabled(True)
    # Exact Windows companion origins only; retain the server's existing defaults.
    os.environ['AMBI_FRONTEND_ORIGINS'] = f'http://127.0.0.1:{PORT},http://localhost:{PORT}'
    os.environ.setdefault("AMBI_DATA_DIR", str(Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "AmbiCompanion" / "data"))
    return create_app(seed=False, auto_start=False)


def main():
    import uvicorn
    uvicorn.run(create_windows_app(), host='127.0.0.1', port=PORT, access_log=False)


if __name__ == '__main__':
    main()
