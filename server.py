"""Run Ambi's local UI: uv run python server.py. Binds only to loopback."""
from __future__ import annotations

import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route, Mount, WebSocketRoute
from starlette.staticfiles import StaticFiles

from ambient import CuePacket
from app_runtime import AppRuntime
from cue_store import CueStore
from memory_store import MemoryStore

ROOT = Path(__file__).resolve().parent


def frontend_origins():
    origins = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (8765, 5173)}
    for origin in filter(None, (part.strip() for part in os.getenv("AMBI_FRONTEND_ORIGINS", "").split(","))):
        parsed = urlsplit(origin)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment or origin != f"{parsed.scheme}://{parsed.netloc}"):
            raise ValueError(f"Invalid AMBI_FRONTEND_ORIGINS entry: {origin}")
        origins.add(origin)
    return origins


def create_app(*, db_path=None, cue_db_path=None, seed=True, runtime_factory=AppRuntime, auto_start=False):
    origins = frontend_origins()
    memory = MemoryStore(db_path or ROOT / "data" / "ambi.sqlite3")
    cue_path = cue_db_path or (Path(f"{db_path}.cues.sqlite3") if db_path is not None
                               else ROOT / "data" / "ambi_cues.sqlite3")
    cue_store = CueStore(cue_path)
    if seed:
        memory.seed_project()
    runtime = runtime_factory(memory)
    token = secrets.token_urlsafe(32)

    def authorized(request):
        origin = request.headers.get("origin")
        return (not origin or origin in origins) and secrets.compare_digest(request.headers.get("x-ambi-token", ""), token)

    async def body(request):
        raw = await request.body()
        if len(raw) > 20000:
            raise ValueError("Request is too large.")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Expected an object.")
        return value

    async def bootstrap(request):
        if request.headers.get("origin") and request.headers["origin"] not in origins:
            return JSONResponse({"error": "Use the local Ambi app."}, status_code=403)
        return JSONResponse({"token": token, "api_configured": bool(os.getenv("OPENAI_API_KEY")),
                             "permissions": runtime.permissions(), "state": runtime.snapshot()},
                            headers={"Cache-Control": "no-store"})

    async def api(request):
        if not authorized(request):
            return JSONResponse({"error": "Open Ambi locally and refresh the page."}, status_code=403)
        action = request.path_params["action"]
        try:
            if request.method == "GET":
                if action == "state":
                    # Same snapshot as bootstrap and /ws, including the
                    # proactive status/reason used to explain silent cues.
                    return JSONResponse(runtime.snapshot())
                if action == "cues":
                    limit = int(request.query_params.get("limit", "50"))
                    if not 1 <= limit <= 100:
                        raise ValueError("Cue history limit must be between 1 and 100.")
                    latest = runtime.camera.latest
                    current = None
                    if latest and monotonic() - latest["received_at"] < 2:
                        current = {key: value for key, value in latest.items() if key != "received_at"}
                        current["age_ms"] = round((monotonic() - latest["received_at"]) * 1000)
                    return JSONResponse({"schema_version": 2, "current": current, "events": cue_store.list(limit)},
                                        headers={"Cache-Control": "no-store"})
                return JSONResponse({"error": "Unknown endpoint"}, status_code=404)
            data = await body(request)
            result = {"ok": True}
            if action == "start":
                await runtime.start(observe_screen=data.get("observe_screen", True) is True)
            elif action == "stop":
                await runtime.stop()
            elif action == "stop-task":
                if runtime.worker:
                    await runtime.worker.stop()
            elif action == "message":
                await runtime.send_text(str(data.get("text", "")))
            elif action == "focus":
                runtime.focus = data.get("enabled") is True
                runtime.suggestion = None
            elif action == "microphone":
                runtime.set_microphone(data.get("enabled") is True)
            elif action == "camera":
                packet = CuePacket.model_validate(data)
                accepted = runtime.camera.ingest(packet)
                event_id = cue_store.record(packet) if accepted else None
                result.update(accepted=accepted, stored=event_id is not None, event_id=event_id)
            elif action == "camera-off":
                runtime.camera.clear()
            elif action == "accept":
                await runtime.accept(str(data.get("id", "")))
            elif action == "dismiss":
                if runtime.suggestion and runtime.suggestion["id"] == data.get("id"):
                    runtime.suggestion = None
            elif action == "memory":
                allowed = {"kind", "title", "body", "source"}
                if set(data) - allowed:
                    raise ValueError("Unexpected memory fields.")
                if any(not isinstance(value, str) for value in data.values()):
                    raise ValueError("Memory fields must be text.")
                memory.put(**data)
            elif action == "memory-delete":
                memory.delete(str(data.get("id", "")))
            elif action == "memory-complete":
                memory.complete(str(data.get("id", "")))
            else:
                return JSONResponse({"error": "Unknown endpoint"}, status_code=404)
            return JSONResponse(result)
        except (ValueError, TypeError, ValidationError, KeyError) as exc:
            return JSONResponse({"error": str(exc)[:250]}, status_code=400)

    async def websocket(ws):
        import asyncio
        from starlette.websockets import WebSocketDisconnect
        protocols = ws.scope.get("subprotocols", [])
        if (ws.headers.get("origin") not in origins or len(protocols) != 2
                or protocols[0] != "ambi" or not secrets.compare_digest(protocols[1], token)):
            await ws.close(code=1008)
            return
        await ws.accept(subprotocol="ambi")
        try:
            while True:
                await ws.send_json(runtime.snapshot())
                await asyncio.sleep(.3)
        except (WebSocketDisconnect, RuntimeError):
            pass

    @asynccontextmanager
    async def lifespan(app):
        if auto_start:
            try:
                await runtime.start()
            except ValueError as exc:
                runtime.status, runtime.error = "error", str(exc)
        yield
        await runtime.stop()
        memory.close()
        cue_store.close()

    routes = [Route("/api/bootstrap", bootstrap), Route("/api/{action}", api, methods=["GET", "POST"]),
              WebSocketRoute("/ws", websocket)]
    ui = ROOT / "ui" / "dist"
    if ui.exists():
        routes.append(Mount("/", StaticFiles(directory=ui, html=True)))
    app = Starlette(routes=routes, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=sorted(origins), allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "X-Ambi-Token"], max_age=600)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    app.state.runtime, app.state.memory, app.state.cue_store = runtime, memory, cue_store
    return app


def main(argv=None):
    import argparse
    import threading
    import time
    import urllib.request
    import webbrowser
    import uvicorn
    from agents import set_tracing_disabled
    parser = argparse.ArgumentParser(description="Ambi's local app")
    parser.add_argument("--open", action="store_true", help="Open the browser once the local server is ready")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", choices=["ellis"], default="ellis",
                      help="Load the isolated Ellis roleplay and start voice (default)")
    mode.add_argument("--no-demo", dest="demo", action="store_const", const=None,
                      help="Use ordinary saved memory and the normal Decisions policy; wait for Start session")
    parser.add_argument("--no-autostart", action="store_true", help="Wait for Start session in demo mode")
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env")
    set_tracing_disabled(True)
    if not (ROOT / "ui" / "dist" / "index.html").exists():
        raise SystemExit("Build the UI first: cd ui && npm ci && npm run build")
    # Do not open a browser onto an unrelated listener or prepare a demo for it.
    import socket
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", 8765))
        except OSError:
            raise SystemExit("Port 8765 is in use. Identify it with lsof -nP -iTCP:8765 -sTCP:LISTEN, then stop that server before launching Ambi.")
    if args.demo:
        from eval.test.demo import create_demo_app
        app = create_demo_app(auto_start=not args.no_autostart)
        print(f"Ellis demo workspace: {app.state.runtime.demo_profile.workspace}", flush=True)
    else:
        app = create_app()
    instruction = "voice starts automatically" if args.demo and not args.no_autostart else "click Start session to enable voice"
    print(f"Ambi is ready at http://127.0.0.1:8765 — {instruction}.", flush=True)
    if args.open:
        def open_when_ready():
            for _ in range(30):
                try:
                    with urllib.request.urlopen("http://127.0.0.1:8765/", timeout=1):
                        webbrowser.open("http://127.0.0.1:8765/")
                        return
                except OSError:
                    time.sleep(.3)
        threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8765, access_log=False)


if __name__ == "__main__":
    main()
