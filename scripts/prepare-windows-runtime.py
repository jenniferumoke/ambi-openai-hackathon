"""Bundle pinned Windows Python, project dependencies and Codex without running them."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/windows'
APP = OUT / 'Ambi-win-x64'
PYTHON_URL = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-x86_64-pc-windows-msvc-install_only_stripped.tar.gz'
PYTHON_HASH = '1f2ab53880fc67ea323398c6388e05af28addc99a8e389209f08a51fdff4b149'
CODEX_URL = 'https://github.com/openai/codex/releases/download/rust-v0.149.0/codex-package-x86_64-pc-windows-msvc.tar.gz'
CODEX_HASH = 'bc470b4b90654c38ee52716056d6d5fc19a49afd08f419328034f4f324536459'


def download(url, digest, target):
    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        urllib.request.urlretrieve(url, target)
    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise SystemExit('Official runtime archive checksum mismatch.')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / 'runtime-downloads'; cache.mkdir(exist_ok=True)
    for url, digest, name in [(PYTHON_URL, PYTHON_HASH, 'python'), (CODEX_URL, CODEX_HASH, 'codex')]:
        archive = cache / (name + '.tar.gz')
        download(url, digest, archive)
        stage = OUT / ('stage-' + name)
        if stage.exists(): shutil.rmtree(stage)
        stage.mkdir()
        with tarfile.open(archive) as tar:
            tar.extractall(stage, filter='data')
        if name == 'python':
            source = next(stage.rglob('python.exe')).parent
            target = APP / 'runtime'
        else:
            metadata = next(stage.rglob('codex-package.json'))
            source = metadata.parent
            target = APP / 'Codex'
        if target.exists(): shutil.rmtree(target)
        shutil.copytree(source, target)
    requirements = OUT / 'runtime-requirements.txt'
    subprocess.run(['uv', 'export', '--locked', '--no-dev', '--no-emit-project', '--format', 'requirements-txt', '--output-file', str(requirements)], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['uv', 'pip', 'install', '--python-version', '3.12', '--python-platform', 'x86_64-pc-windows-msvc', '--target', str(APP / 'runtime/Lib/site-packages'), '--require-hashes', '--no-deps', '-r', str(requirements)], cwd=ROOT, check=True)
    (APP / 'runtime-provenance.json').write_text(json.dumps({'python': {'version': '3.12.16', 'url': PYTHON_URL, 'sha256': PYTHON_HASH}, 'codex': {'version': '0.149.0', 'url': CODEX_URL, 'sha256': CODEX_HASH}}, indent=2))
    print('Windows Python and Codex are bundled; no Windows executable was run on this Mac.')

if __name__ == '__main__': main()
