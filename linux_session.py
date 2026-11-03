"""Read-only prerequisites for the first Linux/X11 desktop preview."""
import json
import os
import shutil


def session_checks(environ=None, which=None):
    env = os.environ if environ is None else environ
    find = shutil.which if which is None else which
    return {
        "X11 session": bool(env.get("DISPLAY")) and
            env.get("XDG_SESSION_TYPE", "x11").lower() == "x11" and
            not bool(env.get("WAYLAND_DISPLAY")),
        "Screenshot utility": bool(find("scrot")),
        "Clipboard utility": bool(find("xclip") or find("xsel")),
    }


if __name__ == "__main__":
    checks = session_checks()
    print(json.dumps(checks))
    raise SystemExit(0 if all(checks.values()) else 1)
