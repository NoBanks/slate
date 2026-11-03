"""Concrete sandbox drivers.

local   - plain subprocess with an empty environment. DEV ONLY, not isolation.
docker  - Docker container: no env, 1 CPU, 1 GB, read-only root, internal
          network where only the proxy is reachable, removed after the task.
msb     - Microsandbox microVM (own kernel via libkrun/KVM): network disabled
          except one rule allowing the host proxy port; destroyed after the task.
"""
from __future__ import annotations

import os
import sys

from .. import config
from .base import WORKER, Sandbox, SandboxError, run

WORKER_IMAGE = os.environ.get("SLATE_WORKER_IMAGE", "slate-worker:latest")
MSB_IMAGE = os.environ.get("SLATE_MSB_IMAGE", "mcr.microsoft.com/playwright/python:v1.58.0-noble")
MSB_PWLIB = os.environ.get("SLATE_MSB_PWLIB", os.path.expanduser("~/pwlib"))  # pip install --target ~/pwlib playwright==1.58.0


class LocalSandbox(Sandbox):
    driver = "local-dev (NOT isolated)"

    async def command(self):
        return [sys.executable, "-u", str(WORKER)]

    def env(self):
        # Empty environment: only what Chromium needs to start. No secrets.
        keep = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "LOCALAPPDATA", "USERPROFILE", "HOME", "APPDATA", "PLAYWRIGHT_BROWSERS_PATH")
        return {k: os.environ[k] for k in keep if k in os.environ}


class DockerSandbox(Sandbox):
    driver = "docker"
    network = "slate-sandbox"

    async def command(self):
        return ["docker", "run", "-i", "--rm", "--name", self.sandbox_id,
                "--cpus", str(self.cpus), "--memory", f"{self.mem_mb}m", "--pids-limit", "256",
                "--network", self.network, "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--read-only", "--tmpfs", "/tmp:size=256m", "--shm-size", "256m",
                "--env-file", os.devnull, WORKER_IMAGE]

    async def destroy(self):
        proof = await super().destroy()
        await run("docker", "rm", "-f", self.sandbox_id, timeout=30)
        code, outp = await run("docker", "ps", "-a", "--filter", f"name={self.sandbox_id}", "--format", "{{.Names}}")
        proof.update(destroyed=(code == 0 and self.sandbox_id not in outp),
                     status="container removed", evidence=f"docker ps -a --filter name={self.sandbox_id} -> '{outp.strip()}'")
        return proof


class MsbSandbox(Sandbox):
    driver = "microsandbox"
    mem_mb = 2048  # headless Chromium; Microsandbox's own Playwright guide uses 2 GB

    async def prepare(self):
        # Airgapped (default deny) except: the host egress proxy port, and DNS so the
        # sandbox can resolve host.microsandbox.internal. Everything else is dropped.
        rule = f"allow@host:tcp:{config.PROXY_PORT},allow@dns"
        # Worker code and the Playwright Python package are mounted READ-ONLY from the host.
        code, outp = await run("msb", "create", "--name", self.sandbox_id, "--cpus", str(self.cpus),
                               "--memory", f"{self.mem_mb}M", "--no-net", "--net-rule", rule,
                               "-v", f"{WORKER.parent}:/slate:ro", "-v", f"{MSB_PWLIB}:/pwlib:ro",
                               "--label", "app=slate", MSB_IMAGE, timeout=900)
        if code != 0:
            raise SandboxError(f"msb create failed: {outp[-600:]}")

    async def command(self):
        return ["msb", "exec", "--stream", "-e", "PYTHONPATH=/pwlib", self.sandbox_id, "--",
                "python3", "-u", "/slate/agent_worker.py"]

    async def destroy(self):
        proof = await super().destroy()
        await run("msb", "rm", "--force", self.sandbox_id, timeout=90)
        code, outp = await run("msb", "ls", "-q")
        proof.update(destroyed=(code == 0 and self.sandbox_id not in outp),
                     status="microVM stopped and removed", evidence=f"msb list contains sandbox: {self.sandbox_id in outp}")
        return proof


def proxy_url_for_sandbox() -> str:
    host = {"msb": "host.microsandbox.internal", "docker": "slate-proxy"}.get(config.SANDBOX, "127.0.0.1")
    return f"http://{host}:{config.PROXY_PORT}"


def make_sandbox(task_id: str) -> Sandbox:
    return {"docker": DockerSandbox, "msb": MsbSandbox}.get(config.SANDBOX, LocalSandbox)(task_id)
