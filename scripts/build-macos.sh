#!/bin/sh
set -eu
AMBI_ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$AMBI_ROOT/desktop/macos"
swift build -c release
AMBI_BIN=$(swift build -c release --show-bin-path)
AMBI_APP="$AMBI_ROOT/artifacts/macos/Ambi.app"
mkdir -p "$AMBI_APP/Contents/MacOS" "$AMBI_APP/Contents/Resources"
cp "$AMBI_ROOT/desktop/shared/icons/ambi.icns" "$AMBI_APP/Contents/Resources/Ambi.icns"
cp "$AMBI_BIN/Ambi" "$AMBI_APP/Contents/MacOS/Ambi"
AMBI_BUILD_ROOT="$AMBI_ROOT" AMBI_BUILD_APP="$AMBI_APP" python3 - <<'PY'
import os, plistlib
from pathlib import Path
root = Path(os.environ['AMBI_BUILD_ROOT'])
app = Path(os.environ['AMBI_BUILD_APP'])
info = dict(CFBundleExecutable='Ambi', CFBundleIdentifier='app.ambi.companion.dev',
            CFBundleName='Ambi', CFBundleDisplayName='Ambi', CFBundlePackageType='APPL',
            CFBundleShortVersionString='0.5.0', CFBundleVersion='5', CFBundleIconFile='Ambi.icns', CFBundleIconName='Ambi', LSMinimumSystemVersion='14.0',
            NSHighResolutionCapable=True, NSPrincipalClass='NSApplication',
            NSMicrophoneUsageDescription='Ambi uses your microphone only when you start a voice session.',
            AmbiBackendDirectory=str(root),
            NSAppTransportSecurity={'NSAllowsLocalNetworking': True})
with (app / 'Contents/Info.plist').open('wb') as f:
    plistlib.dump(info, f)
PY
codesign --force --sign - "$AMBI_APP"
codesign --verify --verbose=2 "$AMBI_APP"
printf '%s\n' "$AMBI_APP"
