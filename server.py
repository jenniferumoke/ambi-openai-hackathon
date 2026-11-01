"""Run Ambi's local UI: uv run python server.py. Binds only to loopback."""
from __future__ import annotations

import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route, Mount, WebSocketRoute
from starlette.staticfiles import StaticFiles

from ambient import CuePacket
from app_runtime import AppRuntime
from memory_store import MemoryStore

ROOT = Path(__file__).resolve().parent


def create_app(*, db_path=None, seed=True, runtime_factory=AppRuntime):
    memory = MemoryStore(db_path or ROOT / "data" / "ambi.sqlite3")
    if seed:
        memory.seed_project()
    runtime = runtime_factory(memory)
    token = secrets.token_urlsafe(32)
    origins = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (8765, 5173)}

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
                    return JSONResponse(runtime.snapshot())
                return JSONResponse({"error": "Unknown endpoint"}, status_code=404)
            data = await body(request)
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
            elif action == "camera":
                packet = CuePacket.model_validate(data)
                runtime.camera.ingest(packet)
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
                memory.put(**data)
            elif action == "memory-delete":
                memory.delete(str(data.get("id", "")))
            elif action == "memory-complete":
                memory.complete(str(data.get("id", "")))
            else:
                return JSONResponse({"error": "Unknown endpoint"}, status_code=404)
            return JSONResponse({"ok": True})
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
        yield
        await runtime.stop()
        memory.close()

    routes = [Route("/api/bootstrap", bootstrap), Route("/api/{action}", api, methods=["GET", "POST"]),
              WebSocketRoute("/ws", websocket)]
    ui = ROOT / "ui" / "dist"
    if ui.exists():
        routes.append(Mount("/", StaticFiles(directory=ui, html=True)))
    app = Starlette(routes=routes, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    app.state.runtime, app.state.memory = runtime, memory
    return app


if __name__ == "__main__":
    import uvicorn
    from agents import set_tracing_disabled
    load_dotenv(ROOT / ".env")
    set_tracing_disabled(True)
    if not (ROOT / "ui" / "dist" / "index.html").exists():
        raise SystemExit("Build the UI first: cd ui && npm ci && npm run build")
    print("Ambi is ready at http://127.0.0.1:8765 — click Start session to enable voice.", flush=True)
    uvicorn.run(create_app(), host="127.0.0.1", port=8765, access_log=False)
