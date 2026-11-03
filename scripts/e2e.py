"""End-to-end run against a live SLATE server: start a task, stream events,
auto-approve (or reject) the final action, then verify the receipt bundle.

  python scripts/e2e.py http://127.0.0.1:8000 [--no-safety] [--red-team] [--reject]
"""
import json
import sys

import httpx

base = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("http") else "http://127.0.0.1:8000"
safety = "--no-safety" not in sys.argv
red = "--red-team" in sys.argv
reject = "--reject" in sys.argv

with httpx.Client(base_url=base, timeout=None) as c:
    tid = c.post("/api/tasks", json={"safety": safety, "red_team": red}).json()["task_id"]
    print("task", tid, "safety", safety, "red_team", red)
    with c.stream("GET", f"/api/tasks/{tid}/events") as s:
        for line in s.iter_lines():
            if not line.startswith("data: "):
                continue
            ev = json.loads(line[6:])
            t = ev["type"]
            if t == "step":
                r = ev["receipt"]
                v = (r.get("verifier") or {}).get("verdict")
                sf = (r.get("safety") or {}).get("injection_detected")
                print(f"  step {r['step']:>2} {r.get('kind'):<10} {json.dumps(r.get('action'))[:90]:<90} verifier={v} injection={sf} {r['hash'][:12]}")
            elif t == "approval_required":
                print("  APPROVAL REQUIRED:", ev.get("summary"), "->", "reject" if reject else "approve")
                c.post(f"/api/tasks/{tid}/approve", json={"approved": not reject})
            elif t in ("alert", "status", "error"):
                print(f"  [{t}] {ev.get('title') or ''} {ev.get('detail') or ev.get('message') or ''}")
            elif t == "egress":
                print(f"  egress {'ALLOW' if ev['allowed'] else 'BLOCK'} {ev['method']} {ev['host']}")
            elif t == "done":
                f = ev["final"]
                print("  DONE outcome:", f.get("outcome"), "| teardown:", json.dumps(f.get("teardown")))
                break
    b = c.get(f"/api/tasks/{tid}/bundle").json()
    rep = c.post("/api/verify", json=b).json()
    print("VERIFY ok:", rep["ok"], "steps:", len(rep["steps"]), "error:", rep.get("error"))
    b["receipts"][1]["intent"] += "x"
    print("TAMPERED ok:", c.post("/api/verify", json=b).json()["ok"])
