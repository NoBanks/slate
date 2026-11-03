"""Sandbox drivers. Each one starts the worker in some isolation boundary and
talks to it over a narrow JSON-lines channel: goto / click / type / observe /
http_request / read_env. No shell, no keys, no model inside.

Uses blocking subprocess pipes in worker threads so it runs on any asyncio
event loop (Windows selector loops cannot spawn asyncio subprocesses)."""
from __future__ import annotations

import asyncio
import json
import subprocess
import uuid
from pathlib import Path

WORKER = Path(__file__).resolve().parent.parent / "worker" / "agent_worker.py"


class SandboxError(RuntimeError):
    pass


class Sandbox:
    driver = "base"
    cpus = 1
    mem_mb = 1024

    def __init__(self, task_id: str):
        self.task_id = task_id
        self.sandbox_id = f"slate-{task_id[:8]}-{uuid.uuid4().hex[:6]}"
        self.proc: subprocess.Popen | None = None

    async def command(self) -> list[str]:
        raise NotImplementedError

    def env(self) -> dict | None:
        return None

    async def prepare(self) -> None:
        """Create the isolation boundary before the worker starts (optional)."""

    async def start(self, proxy_url: str, token: str, qty: int = 250) -> dict:
        await self.prepare()
        cmd = await self.command()
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     env=self.env(), bufsize=0)
        await self._send({"task_id": self.task_id, "proxy": proxy_url, "token": token, "qty": qty})
        ready = await self._recv(timeout=180)
        if not ready.get("ready"):
            raise SandboxError(f"worker failed to start: {ready}")
        return ready

    async def act(self, op: str, **args) -> dict:
        await self._send({"op": op, **args})
        return await self._recv(timeout=60)

    async def _send(self, obj: dict) -> None:
        if not self.proc or self.proc.poll() is not None:
            raise SandboxError("sandbox not running")
        data = (json.dumps(obj) + "\n").encode()

        def w():
            self.proc.stdin.write(data)
            self.proc.stdin.flush()
        await asyncio.to_thread(w)

    async def _recv(self, timeout: float) -> dict:
        try:
            line = await asyncio.wait_for(asyncio.to_thread(self.proc.stdout.readline), timeout=timeout)
        except asyncio.TimeoutError:
            raise SandboxError("worker timed out")
        if not line:
            err = (await asyncio.to_thread(self.proc.stderr.read)).decode(errors="replace")[-800:]
            raise SandboxError(f"worker exited: {err}")
        return json.loads(line)

    async def destroy(self) -> dict:
        """Tear down and return proof for the final receipt."""
        if self.proc and self.proc.poll() is None:
            try:
                await self._send({"op": "quit"})
                await asyncio.wait_for(asyncio.to_thread(self.proc.wait), timeout=10)
            except Exception:
                self.proc.kill()
        return {"sandbox_id": self.sandbox_id, "driver": self.driver, "destroyed": True,
                "status": "worker exited", "evidence": None}


async def run(*cmd: str, timeout: float = 120) -> tuple[int, str]:
    def go():
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return p.returncode, p.stdout.decode(errors="replace")
    try:
        return await asyncio.to_thread(go)
    except subprocess.TimeoutExpired:
        return -1, "timeout"
