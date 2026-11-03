#!/usr/bin/env python3
"""Publish the native Windows companion and its allowlisted local backend."""
from pathlib import Path
from urllib.request import urlretrieve
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
UV_URL = 'https://github.com/astral-sh/uv/releases/download/0.13.6/uv-x86_64-pc-windows-msvc.zip'
UV_SHA256 = 'a2a8820d5eea32f08ef467ef3b7f66883a9b076d5737a2fc2fbb5f458d1bb50f'


def bundle(output):
    destination = output / 'backend'
    files = list(ROOT.glob('*.py')) + [ROOT / name for name in ['pyproject.toml', 'uv.lock', '.env.example']]
    for folder in ['eval', 'bench/fixtures/code', 'ui/dist']:
        files += [p for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
    manifest = []
    for source in files:
        relative = source.relative_to(ROOT)
        assert '.env' not in relative.parts and 'data' not in relative.parts and '.venv' not in relative.parts
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        manifest.append(relative.as_posix())
    (destination / 'files.json').write_text(json.dumps(sorted(manifest), indent=2) + '\n')
    (output / 'BUILD.json').write_text(json.dumps({
        'version': '0.5.0', 'platform': 'win-x64', 'host': 'WPF / WebView2',
        'backend': 'same Python backend as native Mac companion; Windows compatibility audio',
        'uv': '0.13.6', 'backendOrigin': 'http://127.0.0.1:8767', 'uvArchiveSha256': UV_SHA256,
        'voiceAutostart': False, 'screenContextDefault': False,
        'windowsComputerDriver': 'explicit opt-in; primary display; Windows runtime acceptance pending',
        'sourceRepository': 'https://github.com/jenniferumoke/ambi-openai-hackathon',
    }, indent=2) + '\n')
    shutil.copy2(ROOT / 'desktop/windows/README.md', output / 'README.md')
    shutil.copytree(ROOT / 'desktop/shared/licenses', output / 'Licenses', dirs_exist_ok=True)
    shutil.copy2(ROOT / 'LICENSE', output / 'Licenses/Ambi-LICENSE.txt')
    (output / 'Licenses/NOTICE.txt').write_text('Ambi includes OpenAI Codex CLI 0.149.0 under Apache-2.0. Python runtime and dependency license files are included in their distribution directories. No user sign-in or credentials are included.\n')
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle-only', action='store_true')
    args = parser.parse_args()
    output = ROOT / 'artifacts/windows/Ambi-win-x64'
    if not (ROOT / 'ui/dist/companion.html').is_file():
        raise SystemExit('Build ui first: cd ui && npm ci && npm run build')
    if not args.bundle_only:
        uv = ROOT / 'desktop/windows/tools/uv.exe'
        if not uv.is_file():
            archive = ROOT / 'artifacts/windows/uv-windows.zip'
            archive.parent.mkdir(parents=True, exist_ok=True)
            urlretrieve(UV_URL, archive)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != UV_SHA256:
                raise SystemExit('uv checksum mismatch')
            with zipfile.ZipFile(archive) as zipped:
                name = next(n for n in zipped.namelist() if n == 'uv.exe' or n.endswith('/uv.exe'))
                uv.parent.mkdir(parents=True, exist_ok=True)
                uv.write_bytes(zipped.read(name))
        environment = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT='1')
        subprocess.run([os.environ.get('AMBI_DOTNET', 'dotnet'), 'publish', str(ROOT / 'desktop/windows/Ambi.Windows.csproj'),
                        '-c', 'Release', '-r', 'win-x64', '--self-contained', 'true', '-p:PublishSingleFile=false',
                        '-p:RestoreLockedMode=true', '-o', str(output)], env=environment, check=True)
    manifest = bundle(output)
    archive = output.parent / 'Ambi-Windows-Companion-0.5.0.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for path in output.rglob('*'):
            if path.is_file(): zipped.write(path, Path('Ambi') / path.relative_to(output))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(checksum + '  ' + archive.name + '\n')
    print(f'{archive}\nSHA-256 {checksum}\n{len(manifest)} backend files; no environment, local memory or logs bundled.')


if __name__ == '__main__':
    main()
