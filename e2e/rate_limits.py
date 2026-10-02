"""Rate limits, run with low ones (e2e/run.py sets RATE_LIMIT_PARSE=2/hour, RATE_LIMIT_LOGIN=3/minute,
RATE_LIMIT_AI=3/hour): the messages appear where the user acts, and summaries do not count."""
import time

from common import APP_URL as URL
from common import OUT, check, finish
from playwright.sync_api import expect, sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(); errs = []
    # 1) sign-in: 3 wrong attempts are answered normally, the 4th is limited
    pg = b.new_page(viewport={"width": 1400, "height": 950}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL); time.sleep(3)
    msgs = []
    for i in range(4):
        pg.get_by_placeholder("you@example.com").fill("nobody@example.com"); pg.get_by_placeholder("Password").fill("wrong-pass")
        pg.locator("form:has(input[placeholder='you@example.com']) button[type=submit]").click(); time.sleep(1.2)
        msgs.append(pg.locator("form:has(input[placeholder='you@example.com'])").inner_text())
    check("wrong password shows the normal message first", "Invalid email or password" in msgs[0])
    check("4th sign-in attempt shows the rate-limit message", "Too many sign-in attempts" in msgs[3], msgs[3][-120:].replace("\n", " "))
    pg.close()
    # 2) guest board: 2 parses work, the 3rd shows the limit message in the upload panel
    pg = b.new_page(viewport={"width": 1400, "height": 950}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL); time.sleep(3)
    pg.get_by_role("button", name="Continue as guest").click(); time.sleep(1)
    pg.get_by_text("Create your first project").click()
    pg.get_by_placeholder("e.g. SAP S/4HANA Go-Live Programme").fill("Limit test"); pg.get_by_role("button", name="Create project").click()
    expect(pg.locator("main h2").first).to_have_text("Limit test", timeout=20000)
    for i in range(3):
        pg.get_by_placeholder("Meeting title (optional)").fill(f"Meeting {i+1}")
        pg.get_by_placeholder("Paste the raw meeting transcript here.").fill(f"Transcript number {i+1} about the APAC mapping.")
        pg.get_by_role("button", name="Parse transcript").click(); time.sleep(4)
    panel = pg.inner_text("body")
    check("3rd parse shows the rate-limit message", "limit for parsing transcripts" in panel, panel[-160:].replace("\n", " "))
    check("the first two meetings were parsed", pg.locator('[aria-label="Delete task"]').count() >= 4, str(pg.locator('[aria-label="Delete task"]').count()))
    # 3) summaries are written by the server and do not count; 3 subtask generations are allowed, the 4th is not
    time.sleep(3)
    card = pg.locator("div.group").first; card.hover(); card.get_by_role("button", name="Edit task").click(); time.sleep(1)
    texts = []
    for i in range(4):
        pg.locator("button[title='Generate subtasks with AI']").first.click(); time.sleep(0.4)
        pg.get_by_role("button", name="From task details").click(); time.sleep(3)
        texts.append(pg.inner_text("body"))
    check("the first three generations are allowed", all("limit for AI" not in t for t in texts[:3]))
    check("subtask generation beyond the shared AI limit shows the message", "limit for AI summaries and subtask suggestions" in texts[-1], texts[-1][-200:].replace("\n", " "))
    pg.screenshot(path=f"{OUT}/ratelimit_subtasks.png")
    check("no page errors", not errs, "; ".join(errs[:2]))
    b.close()
finish()
