"""Run with: uv run --with pyinstaller==6.16.0 python scripts/build-service.py"""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--name', 'AmbiService',
           '--distpath', str(root / 'artifacts/service'), '--workpath', str(root / 'artifacts/service-build'),
           '--specpath', str(root / 'artifacts/service-build'), '--add-data', f'{root / "ui/dist"}:ui/dist',
           '--collect-all', 'agents', '--collect-submodules', 'uvicorn', '--collect-submodules', 'websockets',
           '--collect-data', 'openai', '--recursive-copy-metadata', 'openai-agents',
           '--collect-all', '_sounddevice_data', str(root / 'companion_service.py')]
subprocess.run(command, cwd=root, check=True)
