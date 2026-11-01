"""Separate local evaluation dashboard. Never starts the product's sensors."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import secrets
import subprocess
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse, HTMLResponse, FileResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect

from bench.paths import ROOT
from bench.profile_lab import ProfileLab, profiles


def create_app(*, output_dir=None, port=8766):
    profile_lab = ProfileLab(Path(output_dir or ROOT / "data/bench") / "profiles")
    token = secrets.token_urlsafe(32)
    origins = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1")}

    def authorized(request):
        return (
            not request.headers.get("origin") or request.headers["origin"] in origins
        ) and secrets.compare_digest(request.headers.get("x-bench-token", ""), token)

    def state():
        return {
            "profile_sessions": profile_lab.sessions(),
            "profile_app": profile_lab.app_state(),
        }

    async def bootstrap(request):
        if request.headers.get("origin") and request.headers["origin"] not in origins:
            return JSONResponse({"error": "Open the local benchmark dashboard."}, 403)
        return JSONResponse(
            {
                "token": token,
                "profiles": profiles(),
                **state(),
            },
            headers={"Cache-Control": "no-store"},
        )

    async def api(request):
        if not authorized(request):
            return JSONResponse(
                {"error": "Refresh the local benchmark dashboard."}, 403
            )
        action = request.path_params["action"]
        try:
            raw = await request.body()
            if len(raw) > 4096:
                return JSONResponse({"error": "Request too large"}, 413)
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError("Expected an object")
            if action == "profile-prepare":
                return JSONResponse(profile_lab.prepare(body.get("profile", "")), 201)
            if action == "profile-launch":
                return JSONResponse(await profile_lab.launch(body.get("id", "")))
            if action == "profile-stop":
                await profile_lab.stop()
                return JSONResponse({"ok": True})
            if action == "profile-editor":
                await asyncio.to_thread(profile_lab.open_editor, body.get("id", ""))
                return JSONResponse({"ok": True})
            if action == "profile-observe":
                return JSONResponse(
                    await profile_lab.observe(
                        body.get("id", ""), body.get("scenario", "")
                    )
                )
            if action == "profile-capture":
                return JSONResponse(
                    await profile_lab.capture(
                        body.get("id", ""), body.get("scenario", "")
                    )
                )
            if action == "profile-review":
                return JSONResponse(
                    profile_lab.review(
                        body.get("id", ""),
                        body.get("scenario", ""),
                        body.get("verdict", ""),
                        body.get("notes", ""),
                    )
                )
            return JSONResponse({"error": "Unknown action"}, 404)
        except (ValueError, KeyError, FileNotFoundError) as exc:
            return JSONResponse({"error": str(exc)[:200]}, 400)
        except (OSError, subprocess.SubprocessError):
            return JSONResponse(
                {
                    "error": "Could not access the profile or open its editor. Open the displayed folder manually."
                },
                400,
            )

    async def profile_source(request):
        session_id, relative = (
            request.path_params["session_id"],
            request.path_params["relative"],
        )
        try:
            if request.url.path.startswith("/profile-view/"):
                return HTMLResponse(
                    profile_lab.source_view(session_id, relative),
                    headers={"Cache-Control": "no-store"},
                )
            path = profile_lab.source_file(session_id, relative)
            media = (
                "application/pdf"
                if path.suffix == ".pdf"
                else "text/html"
                if path.suffix == ".html"
                else "text/plain"
            )
            return FileResponse(
                path,
                media_type=media,
                headers={
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                },
            )
        except (ValueError, FileNotFoundError):
            return JSONResponse({"error": "Profile source not found"}, 404)

    async def profile_report(request):
        if not authorized(request):
            return JSONResponse({"error": "Unauthorized"}, 403)
        try:
            return JSONResponse(
                profile_lab.load(request.path_params["session_id"]),
                headers={"Cache-Control": "no-store"},
            )
        except (ValueError, FileNotFoundError):
            return JSONResponse({"error": "Profile session not found"}, 404)

    async def websocket(ws):
        protocols = ws.scope.get("subprotocols", [])
        if (
            ws.headers.get("origin") not in origins
            or len(protocols) != 2
            or protocols[0] != "ambi-bench"
            or not secrets.compare_digest(protocols[1], token)
        ):
            await ws.close(code=1008)
            return
        await ws.accept(subprotocol="ambi-bench")
        try:
            while True:
                await ws.send_json(state())
                await asyncio.sleep(0.3)
        except (WebSocketDisconnect, RuntimeError):
            pass

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            await profile_lab.stop()

    app = Starlette(
        routes=[
            Route("/api/bootstrap", bootstrap),
            Route("/api/{action}", api, methods=["POST"]),
            Route("/api/profile-report/{session_id}", profile_report),
            Route("/profile-files/{session_id}/{relative:path}", profile_source),
            Route("/profile-view/{session_id}/{relative:path}", profile_source),
            WebSocketRoute("/ws", websocket),
            Mount(
                "/", StaticFiles(directory=Path(__file__).with_name("web"), html=True)
            ),
        ],
        lifespan=lifespan,
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )
    app.state.profile_lab = profile_lab
    return app
