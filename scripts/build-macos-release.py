"""Assemble a source-independent Mac app, sign locally, optionally notarize.

Prerequisite: uv run --with pyinstaller==6.16.0 python scripts/build-service.py
AMBI_SIGN_IDENTITY can select an installed Developer ID identity. Signing never
exports a private key. AMBI_NOTARY_PROFILE optionally names an existing profile.
"""
from pathlib import Path
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.getenv('AMBI_RELEASE_DIR', str(ROOT / 'artifacts/release')))
APP = OUT / 'Ambi.app'
VERSION = '0.5.0'

def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)

def main():
    run('sh', str(ROOT / 'scripts/build-macos.sh'), cwd=ROOT)
    OUT.mkdir(parents=True, exist_ok=True)
    if APP.exists(): shutil.rmtree(APP)
    shutil.copytree(ROOT / 'artifacts/macos/Ambi.app', APP)
    resources = APP / 'Contents/Resources'
    shutil.copytree(ROOT / 'artifacts/service/AmbiService', resources / 'Service')
    codex = Path(os.getenv('AMBI_CODEX_BIN', shutil.which('codex') or '')).resolve()
    if not codex.is_file(): raise SystemExit('A standalone Codex CLI is required for this release bundle.')
    package = codex.parent.parent
    metadata = package / 'codex-package.json'
    if not metadata.is_file() or json.loads(metadata.read_text()).get('version') != '0.149.0':
        raise SystemExit('Release bundling expects the verified standalone Codex 0.149.0 layout.')
    shutil.copytree(package, resources / 'Codex', symlinks=True)
    licenses = resources / 'Licenses'; licenses.mkdir()
    url = 'https://raw.githubusercontent.com/openai/codex/rust-v0.149.0/LICENSE'
    with urllib.request.urlopen(url) as response: (licenses / 'Codex-LICENSE.txt').write_bytes(response.read())
    (licenses / 'NOTICE.txt').write_text('Ambi includes the OpenAI Codex CLI, licensed under Apache-2.0. Codex retains its vendor signature. Python dependency licenses are included in their bundled distribution metadata. No user credentials or local conversation data are bundled.\n')
    info_path = APP / 'Contents/Info.plist'
    info = plistlib.loads(info_path.read_bytes())
    info.pop('AmbiBackendDirectory', None)
    info['CFBundleShortVersionString'] = VERSION
    info['CFBundleVersion'] = '5'
    info_path.write_bytes(plistlib.dumps(info))
    identity = os.getenv('AMBI_SIGN_IDENTITY')
    if not identity:
        listing = subprocess.check_output(['security', 'find-identity', '-v', '-p', 'codesigning'], text=True)
        matches = re.findall(r'([A-F0-9]{40}) "Developer ID Application:[^\n]+', listing)
        if len(matches) == 1: identity = matches[0]
    if not identity: raise SystemExit('No unique Developer ID Application identity. Set AMBI_SIGN_IDENTITY; the unsigned bundle is ready for review.')
    # Sign inner native libraries before the helper and outer application.
    service = resources / 'Service'
    for file in sorted(service.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if file.is_file() and not file.is_symlink():
            kind = subprocess.check_output(['file', '-b', str(file)], text=True)
            if 'Mach-O' in kind:
                run('codesign', '--force', '--options', 'runtime', '--timestamp', '--sign', identity, str(file))
    run('codesign', '--force', '--options', 'runtime', '--timestamp', '--sign', identity, str(APP))
    run('codesign', '--verify', '--deep', '--strict', '--verbose=2', str(APP))
    archive = OUT / f'Ambi-macOS-arm64-{VERSION}.zip'
    run('ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(APP), str(archive))
    notarized = False
    profile = os.getenv('AMBI_NOTARY_PROFILE')
    if profile:
        run('xcrun', 'notarytool', 'submit', str(archive), '--keychain-profile', profile, '--wait')
        run('xcrun', 'stapler', 'staple', str(APP))
        run('spctl', '--assess', '--type', 'execute', '--verbose=2', str(APP))
        run('ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(APP), str(archive))
        notarized = True
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(digest + '  ' + archive.name + '\n')
    (OUT / 'release-status.json').write_text(json.dumps({'version': VERSION, 'architecture': 'arm64', 'developer_id_signed': True, 'notarized': notarized, 'sha256': digest}, indent=2))
    print(f'Release bundle: {APP}\nArchive: {archive}\nDeveloper ID signed; notarized: {notarized}')

if __name__ == '__main__': main()
