"""Account settings for an account with 100 boards (seeded by e2e/run.py): boards with reminders on
are listed first, the list has a fixed height, and search, Select all shown and Clear all shown act
on the matches only."""
import json
import time
import urllib.request

from common import API_URL as API
from common import APP_URL as URL
from common import OUT, check, finish
from playwright.sync_api import sync_playwright


def api(m, path, body=None, tok=None):
    r = urllib.request.Request(API + path, method=m, data=json.dumps(body).encode() if body is not None else None)
    r.add_header("Content-Type", "application/json")
    if tok:
        r.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(r) as x:
        t = x.read()
        return json.loads(t) if t else None


tok = api("POST", "/auth/login", {"email": "many@example.com", "password": "many12345"})["token"]
def on_names(): return sorted(p["name"] for p in api("GET", "/projects", tok=tok) if p["notify_enabled"])
def rows(pg): return pg.locator("section label:has(input[type=checkbox])").all_inner_texts()
with sync_playwright() as p:
    b = p.chromium.launch()
    for vw, vh, tag in [(1400, 900, "desk"), (390, 844, "phone")]:
        pg = b.new_page(viewport={"width": vw, "height": vh}, device_scale_factor=2)
        errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(URL); time.sleep(2)
        pg.get_by_placeholder("you@example.com").fill("many@example.com"); pg.get_by_placeholder("Password").fill("many12345")
        pg.locator("form:has(input[placeholder='you@example.com']) button[type=submit]").click(); time.sleep(2.5)
        pg.locator("button[title='Account settings'] >> visible=true").first.click(); time.sleep(0.8)
        pg.screenshot(path=f"{OUT}/long_{tag}.png")
        if tag == "phone":
            pg.locator("div.max-w-md").evaluate("el => el.scrollTop = el.scrollHeight"); time.sleep(0.3)
            pg.screenshot(path=f"{OUT}/long_phone_bottom.png"); pg.close(); continue
        check("count shows 3 of 100 on", pg.get_by_text("3 of 100 on").count() == 1)
        r = rows(pg)
        check("projects with reminders on are listed first", len(r) == 100 and set(r[:3]) == set(on_names()), str(r[:3]))
        box = pg.locator("div.max-h-60").first.bounding_box()
        check("list is capped in height", box["height"] <= 241, str(box["height"]))
        dlg = pg.locator("div.max-w-md").first
        check("dialog shows Delete account without scrolling far", dlg.evaluate("el => el.scrollHeight") < 1100, str(dlg.evaluate("el => el.scrollHeight")))
        # ticking does not move rows
        before = rows(pg); pg.locator("label", has_text=before[10]).locator("input").click(); time.sleep(1)
        check("ticking leaves the order alone", rows(pg) == before)
        check("count follows ticks", pg.get_by_text("4 of 100 on").count() == 1)
        # search
        pg.get_by_placeholder("Search projects").fill("payroll"); time.sleep(0.3)
        r = rows(pg); check("search narrows the list", len(r) == 10 and all("Payroll" in x for x in r), str(len(r)))
        check("Select all names the shown projects", pg.get_by_role("button", name="Select all shown").count() == 1)
        pg.screenshot(path=f"{OUT}/long_search.png")
        pg.get_by_role("button", name="Clear search").click(); time.sleep(0.3)
        check("clear button empties the search", len(rows(pg)) == 100); pg.get_by_placeholder("Search projects").fill("payroll"); time.sleep(0.3)
        pg.get_by_role("button", name="Select all shown").click(); time.sleep(2)
        on = on_names(); check("Select all shown ticks only the matches", all(n in on for n in r) and len(on) == 4 + sum(1 for n in r if n not in set(before[:3]) | {before[10]}), str(len(on)))
        pg.get_by_role("button", name="Clear all shown").click(); time.sleep(2)
        on2 = on_names(); check("Clear all shown clears only the matches", not any("Payroll" in n for n in on2) and len(on2) == len([n for n in on if "Payroll" not in n]), str(on2))
        pg.get_by_placeholder("Search projects").fill("zzz"); time.sleep(0.3)
        check("no match message", pg.get_by_text("No projects match").count() == 1 and pg.get_by_role("button", name="Select all").count() == 0)
        pg.keyboard.press("Escape"); time.sleep(0.4)
        pg.locator("button[title='Account settings'] >> visible=true").first.click(); time.sleep(0.8)
        check("search clears on reopen", pg.get_by_placeholder("Search projects").input_value() == "" and len(rows(pg)) == 100)
        check("no page errors", not errs, str(errs[:2])); pg.close()
    b.close()
finish()
