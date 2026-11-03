"""Egress proxy: the sandbox's only road to the network.

The sandbox's network is locked so it can reach nothing except this proxy.
Each task authenticates with its own token (Proxy-Authorization basic auth),
gets its own host allowlist, and every request, allowed or blocked, is
reported back so it lands in the task's receipts.
"""
from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlsplit

BLOCK_BODY = b"Blocked by SLATE egress policy\n"


@dataclass
class TaskPolicy:
    task_id: str
    token: str
    allowlist: list[str]
    on_event: Callable[[dict], None]
    blocked: list[dict] = field(default_factory=list)
    allowed: list[dict] = field(default_factory=list)

    def permits(self, host: str) -> bool:
        host = host.lower().rstrip(".")
        return any(host == a or host.endswith("." + a) for a in self.allowlist)


class EgressProxy:
    def __init__(self, host: str = "127.0.0.1", port: int = 8899):
        self.host, self.port = host, port
        self.policies: dict[str, TaskPolicy] = {}
        self._server: asyncio.base_events.Server | None = None

    def register(self, policy: TaskPolicy) -> None:
        self.policies[policy.token] = policy

    def unregister(self, token: str) -> None:
        self.policies.pop(token, None)

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        if self.port == 0:
            self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def _policy_for(self, headers: dict[str, str]) -> TaskPolicy | None:
        auth = headers.get("proxy-authorization", "")
        if not auth.lower().startswith("basic "):
            return None
        try:
            user_pass = base64.b64decode(auth[6:]).decode()
        except ValueError:
            return None
        _, _, token = user_pass.partition(":")
        return self.policies.get(token)

    def _record(self, policy: TaskPolicy | None, method: str, host: str, port: int, allowed: bool, url: str = ""):
        ev = {"type": "egress", "method": method, "host": host, "port": port,
              "allowed": allowed, "url": url[:300], "ts": time.time()}
        if policy:
            (policy.allowed if allowed else policy.blocked).append(ev)
            try:
                policy.on_event(ev)
            except Exception:
                pass

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=15)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
            writer.close()
            return
        lines = head.decode("latin-1").split("\r\n")
        try:
            method, target, version = lines[0].split(" ", 2)
        except ValueError:
            writer.close()
            return
        headers = {}
        for ln in lines[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        policy = self._policy_for(headers)
        if policy is None:
            writer.write(b'HTTP/1.1 407 Proxy Authentication Required\r\nProxy-Authenticate: Basic realm="slate"\r\nContent-Length: 0\r\n\r\n')
            await writer.drain()
            writer.close()
            return

        if method.upper() == "CONNECT":
            host, _, port_s = target.rpartition(":")
            port = int(port_s or 443)
            host = host.strip("[]")
            if not policy.permits(host):
                self._record(policy, "CONNECT", host, port, False, f"https://{host}")
                await self._deny(writer)
                return
            try:
                up_r, up_w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=10)
            except (OSError, asyncio.TimeoutError):
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                writer.close()
                return
            self._record(policy, "CONNECT", host, port, True, f"https://{host}")
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            await self._pipe(reader, writer, up_r, up_w)
            return

        parts = urlsplit(target)
        host = (parts.hostname or "").lower()
        port = parts.port or 80
        if not host or not policy.permits(host):
            self._record(policy, method, host, port, False, target)
            await self._deny(writer)
            return
        try:
            up_r, up_w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=10)
        except (OSError, asyncio.TimeoutError):
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            writer.close()
            return
        self._record(policy, method, host, port, True, target)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        out = [f"{method} {path} {version}"]
        for ln in lines[1:]:
            if ln and not ln.lower().startswith(("proxy-", "connection:")):
                out.append(ln)
        out.append("Connection: close")
        up_w.write(("\r\n".join(out) + "\r\n\r\n").encode("latin-1"))
        await up_w.drain()
        await self._pipe(reader, writer, up_r, up_w)

    async def _deny(self, writer: asyncio.StreamWriter):
        writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\nContent-Length: "
                     + str(len(BLOCK_BODY)).encode() + b"\r\nConnection: close\r\n\r\n" + BLOCK_BODY)
        try:
            await writer.drain()
        finally:
            writer.close()

    async def _pipe(self, cr, cw, ur, uw):
        async def copy(r, w):
            try:
                while data := await r.read(65536):
                    w.write(data)
                    await w.drain()
            except (ConnectionError, asyncio.CancelledError):
                pass
            finally:
                try:
                    w.close()
                except Exception:
                    pass
        await asyncio.gather(copy(cr, uw), copy(ur, cw))
