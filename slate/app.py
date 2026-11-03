"""SLATE web app + API (FastAPI). Serves the UI, the vendor demo sites
(by Host header in production, by path in local dev), and the public verifier."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .orchestrator import TaskManager, vendor_list
from .proxy import EgressProxy
from .receipts import Signer, verify_bundle

WEB = config.ROOT / "web"
VENDORS = config.ROOT / "vendors"
DEFAULT_GOAL = ("Get a price for 250 units of 'Industrial LED panel, 600x600, 40W' from Brightline Supply, "
                "Lumen Depot and Northfield Electric, pick the cheapest safe vendor, and fill out its quote request form.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    signer = Signer.load_or_create(config.DATA_DIR / "keys" / "server_ed25519.hex")
    proxy = EgressProxy(host=config.env("SLATE_PROXY_BIND", "127.0.0.1"), port=config.PROXY_PORT)
    await proxy.start()
    app.state.signer, app.state.proxy = signer, proxy
    app.state.tasks = TaskManager(signer, proxy)
    yield
    await proxy.stop()


app = FastAPI(title="SLATE", lifespan=lifespan)


@app.middleware("http")
async def vendor_hosts(request: Request, call_next):
    """slate-<vendor>.nohumannearby.com serves that vendor's static site."""
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if host.startswith("slate-") and host.split(".")[0][6:] in ("brightline", "lumen", "northfield"):
        slug = host.split(".")[0][6:]
        name = request.url.path.strip("/") or "index.html"
        f = (VENDORS / slug / name).resolve()
        if VENDORS.resolve() in f.parents and f.is_file():
            return FileResponse(f)
        return JSONResponse({"error": "not found"}, status_code=404)
    return await call_next(request)


app.mount("/static", StaticFiles(directory=WEB), name="static")
app.mount("/vendors", StaticFiles(directory=VENDORS, html=True), name="vendors")


@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


@app.get("/verify")
async def verify_page():
    return FileResponse(WEB / "verify.html")


@app.get("/api/info")
async def info(request: Request):
    tm = request.app.state.tasks
    b = tm.tasks and next(iter(tm.tasks.values())).brain.models
    return {"pubkey": request.app.state.signer.pubkey_hex, "llm": config.LLM_MODE, "sandbox": config.SANDBOX,
            "inference": config.INFERENCE_BASE_URL, "models": b or {"planner": config.PLANNER_MODEL,
            "verifier": config.VERIFIER_MODEL, "safety": config.SAFETY_MODEL}, "vendors": vendor_list(),
            "default_goal": DEFAULT_GOAL}


@app.get("/api/pubkey")
async def pubkey(request: Request):
    return {"pubkey": request.app.state.signer.pubkey_hex, "alg": "ed25519"}


@app.post("/api/tasks")
async def create_task(request: Request):
    body = await request.json()
    running = [t for t in request.app.state.tasks.tasks.values() if t.status == "running"]
    if len(running) >= 2:
        raise HTTPException(429, "Two tasks are already running. Try again in a minute.")
    t = request.app.state.tasks.create((body.get("goal") or DEFAULT_GOAL)[:2000],
                                       bool(body.get("safety", True)), bool(body.get("red_team", False)))
    return {"task_id": t.id}


def _task(request: Request, task_id: str):
    t = request.app.state.tasks.tasks.get(task_id)
    if not t:
        raise HTTPException(404, "unknown task")
    return t


@app.get("/api/tasks/{task_id}/events")
async def events(request: Request, task_id: str):
    t = _task(request, task_id)
    q = t.subscribe()

    async def gen():
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(ev)}\n\n"
                if ev.get("type") in ("done",):
                    break
        finally:
            if q in t.subscribers:
                t.subscribers.remove(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/tasks/{task_id}/approve")
async def approve(request: Request, task_id: str):
    body = await request.json()
    ok = _task(request, task_id).approve(bool(body.get("approved")))
    return {"ok": ok}


@app.get("/api/tasks/{task_id}/bundle")
async def bundle(request: Request, task_id: str):
    f = config.DATA_DIR / "bundles" / f"{task_id}.json"
    if not f.exists():
        raise HTTPException(404, "bundle not ready")
    return FileResponse(f, media_type="application/json", filename=f"slate-receipts-{task_id}.json")


@app.get("/api/screens/{name}")
async def screen(name: str):
    digest = name.removesuffix(".png")
    if len(digest) != 64 or not all(c in "0123456789abcdef" for c in digest):
        raise HTTPException(400, "bad name")
    f = config.DATA_DIR / "screens" / f"{digest}.png"
    if not f.exists():
        raise HTTPException(404, "not found")
    return FileResponse(f, media_type="image/png")


@app.post("/api/verify")
async def verify(request: Request):
    try:
        b = await request.json()
    except Exception:
        return {"ok": False, "error": "not JSON", "steps": []}
    if isinstance(b, dict) and "bundle" in b and isinstance(b["bundle"], dict):
        b = b["bundle"]
    screenshots = {}
    for r in (b.get("receipts") or []) if isinstance(b, dict) else []:
        d = ((r or {}).get("observation") or {}).get("screenshot_sha256")
        if d and len(d) == 64 and all(c in "0123456789abcdef" for c in d):
            f = config.DATA_DIR / "screens" / f"{d}.png"
            if f.exists():
                screenshots[d] = f.read_bytes()
    report = verify_bundle(b, screenshots if screenshots else None)
    report["server_pubkey"] = request.app.state.signer.pubkey_hex
    report["signed_by_this_server"] = report.get("pubkey") == report["server_pubkey"]
    return report
