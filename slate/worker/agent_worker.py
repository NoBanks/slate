"""SLATE worker. Runs INSIDE the sandbox.

Speaks JSON lines on stdin/stdout. The first line is an init message with the
proxy address and a one-time proxy token (sent over stdin, never via env vars).
There is no shell action and no model here: the brain stays outside.
"""
import base64
import json
import os
import sys

from playwright.sync_api import sync_playwright

PAGE_JS = """() => {
  const fields = [...document.querySelectorAll('input,textarea,select,button')].slice(0, 40).map(e => ({
    tag: e.tagName.toLowerCase(), id: e.id || null, name: e.name || null, type: e.type || null,
    label: (e.labels && e.labels[0] && e.labels[0].innerText) || e.placeholder || e.innerText || null,
    value: e.value || null }));
  const rows = [...document.querySelectorAll('#pricing [data-qty-min]')].map(r => ({
    qty_min: Number(r.dataset.qtyMin), unit_price: Number(r.dataset.unitPrice) }));
  // textContent (not innerText) so hidden text is visible to the safety screen
  return { title: document.title, text: document.body ? document.body.textContent.replace(/\\s+/g, ' ').trim() : '',
           visible_text: document.body ? document.body.innerText : '', fields, pricing: rows };
}"""


def out(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def observe(page, qty):
    info = page.evaluate(PAGE_JS)
    shot = page.screenshot(type="png", full_page=False)
    tiers = sorted(info.get("pricing") or [], key=lambda r: r["qty_min"])
    price = None
    for t in tiers:
        if qty >= t["qty_min"]:
            price = t["unit_price"]
    return {"url": page.url, "title": info["title"], "text": info["text"][:20000],
            "visible_text": info["visible_text"][:8000], "fields": info["fields"],
            "pricing": tiers, "price_for_qty": price,
            "screenshot_b64": base64.b64encode(shot).decode()}


def main():
    init = json.loads(sys.stdin.readline())
    qty = int(init.get("qty", 250))
    proxy = None
    if init.get("proxy"):
        proxy = {"server": init["proxy"], "username": init.get("task_id", "task"), "password": init.get("token", "")}
    with sync_playwright() as p:
        args = ["--proxy-bypass-list=<-loopback>"]  # route even localhost through the proxy
        if os.name != "nt":
            args += ["--no-sandbox", "--disable-dev-shm-usage"]
        browser = p.chromium.launch(headless=True, proxy=proxy, args=args)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800}, ignore_https_errors=False,
                                  proxy=proxy)
        page = ctx.new_page()
        page.set_default_timeout(15000)
        out({"ok": True, "ready": True, "pid": os.getpid()})
        for line in sys.stdin:
            try:
                cmd = json.loads(line)
                op = cmd.get("op")
                result = {}
                if op == "goto":
                    resp = page.goto(cmd["url"], wait_until="domcontentloaded")
                    result["status"] = resp.status if resp else None
                elif op == "click":
                    page.click(cmd["selector"])
                    page.wait_for_load_state("domcontentloaded")
                elif op == "type":
                    page.fill(cmd["selector"], cmd["text"])
                elif op == "http_request":
                    r = ctx.request.fetch(cmd["url"], method=cmd.get("method", "GET"),
                                          data=cmd.get("body"), fail_on_status_code=False)
                    result = {"status": r.status, "body": r.text()[:500]}
                elif op == "read_env":
                    result = {"env": dict(os.environ)}
                elif op == "observe":
                    pass
                elif op == "quit":
                    out({"ok": True, "bye": True})
                    break
                else:
                    raise ValueError(f"unknown op {op}")
                out({"ok": True, "result": result, "observation": observe(page, qty)})
            except Exception as e:  # report, never crash the loop
                try:
                    obs = observe(page, qty)
                except Exception:
                    obs = None
                out({"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "observation": obs})
        browser.close()


if __name__ == "__main__":
    main()
