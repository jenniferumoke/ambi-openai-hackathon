"""Separate local evaluation dashboard. Never starts the product's sensors."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import secrets
import subprocess
from pathlib import Path

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect

from bench.runner import BenchRunner, RunConfig
from bench.workspaces import WorkspaceLab


def create_app(*, output_dir=None, port=8766):
    runner = BenchRunner(output_dir)
    lab = WorkspaceLab(runner.output_dir / "workspaces")
    token = secrets.token_urlsafe(32)
    origins = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1")}

    def authorized(request):
        return (not request.headers.get("origin") or request.headers["origin"] in origins) and secrets.compare_digest(request.headers.get("x-bench-token", ""), token)

    def state():
        return {"run": runner.current, "revision": runner.revision, "history": runner.history(),
                "workspaces": lab.list(), "restart_required": runner.catalog()["restart_required"]}

    async def bootstrap(request):
        if request.headers.get("origin") and request.headers["origin"] not in origins:
            return JSONResponse({"error": "Open the local benchmark dashboard."}, 403)
        return JSONResponse({"token": token, "catalog": runner.catalog(), "workspace_catalog": lab.catalog(), **state()},
                            headers={"Cache-Control": "no-store"})

    async def api(request):
        if not authorized(request):
            return JSONResponse({"error": "Refresh the local benchmark dashboard."}, 403)
        action = request.path_params["action"]
        try:
            raw = await request.body()
            if len(raw) > 4096:
                return JSONResponse({"error": "Request too large"}, 413)
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError("Expected an object")
            if action == "run":
                run_id = runner.start(RunConfig.model_validate(body))
                return JSONResponse({"id": run_id}, 202)
            if action == "cancel":
                await runner.cancel()
            elif action == "prepare":
                return JSONResponse(lab.prepare(body.get("scenario", "")), 201)
            elif action == "verify":
                return JSONResponse(await asyncio.to_thread(lab.verify, body.get("id", "")))
            elif action == "open-workspace":
                await asyncio.to_thread(lab.open_editor, body.get("id", ""))
            else:
                return JSONResponse({"error": "Unknown action"}, 404)
            return JSONResponse({"ok": True})
        except ValidationError:
            return JSONResponse({"error": "Invalid benchmark configuration."}, 400)
        except (ValueError, KeyError, FileNotFoundError) as exc:
            return JSONResponse({"error": str(exc)[:200]}, 400)
        except (OSError, subprocess.SubprocessError):
            return JSONResponse({"error": "Could not access the workspace or open VS Code. Open the displayed folder manually."}, 400)

    async def report(request):
        if not authorized(request):
            return JSONResponse({"error": "Unauthorized"}, 403)
        try:
            result = runner.read_report(request.path_params["run_id"])
            return JSONResponse(result, headers={"Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="ambi-bench-report.json"'})
        except (ValueError, FileNotFoundError):
            return JSONResponse({"error": "Report not found"}, 404)

    async def websocket(ws):
        protocols = ws.scope.get("subprotocols", [])
        if (ws.headers.get("origin") not in origins or len(protocols) != 2 or protocols[0] != "ambi-bench"
                or not secrets.compare_digest(protocols[1], token)):
            await ws.close(code=1008)
            return
        await ws.accept(subprotocol="ambi-bench")
        try:
            while True:
                await ws.send_json(state())
                await asyncio.sleep(.3)
        except (WebSocketDisconnect, RuntimeError):
            pass

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await runner.cancel()

    app = Starlette(routes=[Route("/api/bootstrap", bootstrap), Route("/api/{action}", api, methods=["POST"]),
                           Route("/api/report/{run_id}", report), WebSocketRoute("/ws", websocket),
                           Mount("/", StaticFiles(directory=Path(__file__).with_name("web"), html=True))], lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
    app.state.runner, app.state.lab = runner, lab
    return app
