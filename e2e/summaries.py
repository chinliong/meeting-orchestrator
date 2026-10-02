"""Meeting summaries (simulated: 1.5 s each; a transcript containing SUMFAIL fails): written after
the tasks, failure and Try again, after a reload, several meetings, view-only links, phone width."""
import json
import time

from common import APP_URL as URL
from common import OUT, check, finish
from playwright.sync_api import expect, sync_playwright

FILTER = "div.flex-wrap:has(> span:text-is('Filter'))"
def cards(pg): return pg.locator('[aria-label="Delete task"]').count()
def mbtn(pg): return pg.locator(f"{FILTER} button[aria-haspopup='true']").first
def pick(pg, label):
    """Show one meeting (or All meetings): clear any earlier choice first, since ticking adds to it."""
    if label != "All meetings" and "All meetings" not in mbtn(pg).inner_text():
        mbtn(pg).click(); time.sleep(0.3)
        pg.locator(f"{FILTER} div.z-40 button", has_text="All meetings").first.click(); time.sleep(0.4)
    mbtn(pg).click(); time.sleep(0.3)
    pg.locator(f"{FILTER} div.z-40 button", has_text=label).first.click(); time.sleep(0.4)
    if pg.locator(f"{FILTER} div.z-40").count():  # the list stays open after ticking a meeting
        pg.keyboard.press("Escape")
    time.sleep(0.4)
def tick(pg, labels):
    """Tick several meetings at once."""
    mbtn(pg).click(); time.sleep(0.3)
    for label in labels:
        pg.locator(f"{FILTER} div.z-40 li", has_text=label).locator("button[role=checkbox]").click(); time.sleep(0.3)
    pg.keyboard.press("Escape"); time.sleep(0.5)
def card(pg): return pg.locator("section[aria-label^='Summary of']")
def card_text(pg): return card(pg).inner_text() if card(pg).count() else ""
def paste(pg, text, title=""):
    pg.get_by_placeholder("Meeting title (optional)").fill(title)
    pg.get_by_placeholder("Paste the raw meeting transcript here.").fill(text)
    pg.get_by_role("button", name="Parse transcript").click()
def wait(fn, t=15):
    end = time.time() + t
    while time.time() < end:
        if fn(): return True
        time.sleep(0.2)
    return False
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1400, "height": 1000}, device_scale_factor=2)
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL); pg.get_by_role("button", name="Continue as guest").click()
    pg.get_by_text("Create your first project").click()
    pg.get_by_placeholder("e.g. SAP S/4HANA Go-Live Programme").fill("Board S"); pg.get_by_role("button", name="Create project").click()
    expect(pg.locator("main h2").first).to_have_text("Board S")
    check("no summary card on an empty board", card(pg).count() == 0)

    paste(pg, "normal meeting", "Steering")
    seen_working = wait(lambda: "Writing a summary" in card_text(pg), 8)
    check("after parsing, the tasks are on the board while the summary is still being written",
          seen_working and cards(pg) == 2, f"cards={cards(pg)}")
    pg.screenshot(path=f"{OUT}/sum_working.png")
    done = wait(lambda: "The team met for" in card_text(pg), 10)
    t = card_text(pg)
    check("the summary arrives: labelled AI summary, named and dated, with the overview only",
          done and "AI summary" in t and "Steering" in t and "The team met for Steering" in t and "DECIDED" not in t and "2026" in t, t[:140].replace("\n", " | "))
    check("it says it is AI-written and that the board shows current progress", "Written by AI" in t and "where the work stands now" in t)
    check("the board is unfiltered (All meetings); an editor sees Rewrite, and the only meeting's card has no hide button",
          "All meetings" in mbtn(pg).inner_text() and card(pg).get_by_role("button", name="Rewrite").count() == 1
          and card(pg).get_by_role("button", name="Hide summary").count() == 0)
    pg.screenshot(path=f"{OUT}/sum_done.png")
    card(pg).locator("button[aria-expanded]").click(); time.sleep(0.3)
    check("the header collapses the card to one line", "The team met for" not in card_text(pg) and "Steering" in card_text(pg))
    card(pg).locator("button[aria-expanded]").click(); time.sleep(0.3)
    pg.reload(); expect(pg.locator("main h2").first).to_have_text("Board S"); wait(lambda: cards(pg) == 2)
    check("after a reload, a board's only meeting still shows its summary under All meetings",
          wait(lambda: "The team met for Steering" in card_text(pg), 5) and "All meetings" in mbtn(pg).inner_text())

    pick(pg, "Steering")
    t = card_text(pg)
    check("picking the meeting in the filter shows its summary, without a hide button",
          "The team met for Steering" in t and card(pg).get_by_role("button", name="Hide summary").count() == 0)
    pick(pg, "All meetings")
    check("back on All meetings, the only meeting's card is still shown", "The team met for Steering" in card_text(pg))

    # A summary that fails: the tasks are still added, and the card offers Try again.
    paste(pg, "SUMFAIL meeting", "Flaky")
    failed = wait(lambda: "Couldn't write a summary" in card_text(pg), 10)
    check("a failed summary still adds the tasks and says so, with Try again",
          failed and cards(pg) == 4 and card(pg).get_by_role("button", name="Try again").count() == 1, card_text(pg)[:100].replace("\n", " | "))
    pg.screenshot(path=f"{OUT}/sum_failed.png")
    check("with two meetings, the just-added meeting's card can be hidden", card(pg).get_by_role("button", name="Hide summary").count() == 1)
    card(pg).get_by_role("button", name="Try again").click()
    check("Try again writes again (and here fails again, without touching the tasks)",
          wait(lambda: "Writing a summary" in card_text(pg), 3) and wait(lambda: "Couldn't write" in card_text(pg), 8) and cards(pg) == 4)

    # After a reload the server's failed attempt is remembered, so the editor still sees it with Try again.
    pg.reload(); expect(pg.locator("main h2").first).to_have_text("Board S"); wait(lambda: cards(pg) == 4)
    check("with two meetings, after a reload no card shows until a meeting is picked", card(pg).count() == 0)
    pick(pg, "Flaky")
    t = card_text(pg)
    check("after a reload, a summary the server could not write still says so, with Try again",
          "Couldn't write a summary" in t and card(pg).get_by_role("button", name="Try again").count() == 1, t[:80])
    pg.screenshot(path=f"{OUT}/sum_none.png")
    pick(pg, "Steering")
    check("a saved summary is still there after a reload", "The team met for Steering" in card_text(pg))
    card(pg).get_by_role("button", name="Rewrite").click()
    check("Rewrite writes it again", wait(lambda: "Writing a summary" in card_text(pg), 3) and wait(lambda: "The team met for" in card_text(pg), 8))

    # Two meetings chosen: one card listing both, folded, opening one at a time.
    pick(pg, "All meetings")
    tick(pg, ["Steering", "Flaky"])
    lst = pg.locator("section[aria-label='Summaries of the chosen meetings']")
    rows = lst.locator("button[aria-expanded]")
    check("two meetings chosen: one summary list with a row each, all folded",
          lst.count() == 1 and rows.count() == 2 and card(pg).count() == 0
          and all(r.get_attribute("aria-expanded") == "false" for r in rows.all()))
    rows.filter(has_text="Steering").click(); time.sleep(0.4)
    check("opening a row shows its summary", "The team met for Steering" in lst.inner_text())
    rows.filter(has_text="Flaky").click(); time.sleep(0.4)
    check("opening another row closes the first", "The team met for Steering" not in lst.inner_text()
          and "Couldn't write a summary" in lst.inner_text())
    check("the stats name both meetings", "Steering and Flaky" in pg.locator("section[aria-label='Board summary'] p").first.inner_text()
          or "Flaky and Steering" in pg.locator("section[aria-label='Board summary'] p").first.inner_text())
    pick(pg, "All meetings")

    # View-only link: summaries can be read, not written.
    ws = json.loads(pg.evaluate("localStorage.getItem('mo.guestWorkspaces')"))
    view_token = ws[0]["view_token"]
    v = b.new_page(viewport={"width": 1400, "height": 1000})
    v.goto(f"{URL}?w={view_token}"); wait(lambda: cards(v) == 4)
    pick(v, "Steering")
    t = card_text(v)
    check("a view-only link can read a summary, without Rewrite", "The team met for Steering" in t and card(v).get_by_role("button", name="Rewrite").count() == 0)
    pick(v, "Flaky")
    t = card_text(v)
    check("a view-only link sees 'No summary has been written' with no button",
          "No summary has been written" in t and card(v).get_by_role("button", name="Summarise this meeting").count() == 0, t[:80])

    # Deleting the meeting whose card is showing removes the card.
    pick(pg, "Flaky")
    mbtn(pg).click(); time.sleep(0.3)
    pg.locator(f"{FILTER} div.z-40 li", has_text="Flaky").locator("[aria-label^='Delete meeting']").click()
    pg.get_by_role("button", name="Delete meeting").click()
    check("deleting that meeting removes its tasks, and the remaining only meeting's summary shows",
          wait(lambda: cards(pg) == 2 and "The team met for Steering" in card_text(pg), 8))

    # Phone width.
    m = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    m.goto(f"{URL}?w={view_token}"); wait(lambda: cards(m) == 2)
    check("a view-only link to a one-meeting board shows its summary without picking it",
          wait(lambda: "The team met for Steering" in card_text(m), 5))
    card(m).scroll_into_view_if_needed(); time.sleep(0.3)
    width = m.evaluate("document.documentElement.scrollWidth")
    check("on a phone the card fits the screen", width <= 390, f"scrollWidth={width}")
    card(m).screenshot(path=f"{OUT}/sum_phone.png")
    check("no page errors", not errs, "; ".join(errs[:2]))
    b.close()
finish()
