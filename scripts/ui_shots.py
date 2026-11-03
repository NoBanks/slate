"""Drive the SLATE UI in a headless browser and save screenshots.

  python scripts/ui_shots.py http://127.0.0.1:8000 OUT_DIR [--red-team]
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

base, out = sys.argv[1], Path(sys.argv[2])
red = "--red-team" in sys.argv
out.mkdir(parents=True, exist_ok=True)
tag = "redteam" if red else "normal"

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
    errors = []
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base + "/")
    page.screenshot(path=str(out / f"{tag}_0_home.png"))
    if red:
        page.click("label[for=safety]")
        page.click("label[for=redteam]")
    page.click("#start")
    approved = False
    t0 = time.time()
    shot_mid = False
    while time.time() - t0 < 180:
        time.sleep(1)
        if not shot_mid and page.locator(".card, .step").count() >= 5:
            page.screenshot(path=str(out / f"{tag}_1_running.png"))
            shot_mid = True
        btn = page.locator("text=Reject" if red else "text=Approve").first
        if not approved and btn.count() and btn.is_visible():
            page.screenshot(path=str(out / f"{tag}_2_approval.png"))
            btn.click()
            approved = True
        if page.locator("text=/Download receipt bundle/i").count() and page.locator("text=/Download receipt bundle/i").first.is_visible():
            break
    time.sleep(1.5)
    page.screenshot(path=str(out / f"{tag}_3_done.png"), full_page=True)
    print("errors:", errors[:5])
    b.close()
