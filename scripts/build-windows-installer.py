"""Compile the per-user installer on Windows; sign only with an installed cert.

AMBI_SIGN_CERT is a certificate-store thumbprint (never a PFX/password).
AMBI_SIGN_TIMESTAMP must be the certificate provider's HTTPS timestamp URL.
AMBI_ISCC and AMBI_SIGNTOOL may name installed tools. No keys are exported.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    if sys.platform != 'win32':
        raise SystemExit('Compile and verify the installer on Windows. No installer was produced on this platform.')
    compiler = os.getenv('AMBI_ISCC') or shutil.which('ISCC.exe')
    if not compiler: raise SystemExit('Set AMBI_ISCC to the installed Inno Setup compiler.')
    source = ROOT / 'artifacts/windows/Ambi-win-x64'
    if not (source / 'runtime/python.exe').is_file() or not (source / 'Codex/bin/codex.exe').is_file():
        raise SystemExit('Prepare the complete portable Windows runtime first.')
    cert, timestamp = os.getenv('AMBI_SIGN_CERT'), os.getenv('AMBI_SIGN_TIMESTAMP')
    tool = os.getenv('AMBI_SIGNTOOL') or shutil.which('signtool.exe')
    if cert and (not tool or not timestamp or not timestamp.startswith('https://')):
        raise SystemExit('Signing requires signtool and the provider HTTPS timestamp URL.')
    def sign(path):
        subprocess.run([tool, 'sign', '/sha1', cert, '/fd', 'SHA256', '/tr', timestamp, '/td', 'SHA256', str(path)], check=True)
        subprocess.run([tool, 'verify', '/pa', '/all', str(path)], check=True)
    if cert: sign(source / 'Ambi.exe')
    subprocess.run([compiler, f'/DSourceDir={source}', str(ROOT / 'desktop/windows/installer/Ambi.iss')], check=True)
    setup = ROOT / 'artifacts/windows/Ambi-Setup-0.5.0-x64.exe'
    if cert: sign(setup)
    digest = hashlib.sha256(setup.read_bytes()).hexdigest()
    setup.with_suffix('.exe.sha256').write_text(digest + '  ' + setup.name + '\n')
    setup.with_suffix('.exe.status.json').write_text(json.dumps({'signed': bool(cert), 'sha256': digest, 'version': '0.5.0'}, indent=2))
    print(f'{setup}\nSigned and verified: {bool(cert)}')

if __name__ == '__main__': main()
