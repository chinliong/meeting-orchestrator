"""Export to spreadsheet on the seeded demo board: the options box, the file's format (a byte-order
mark and CRLF line endings, so Excel opens it correctly), the columns, filtered exports, and the
phone layout."""
import time

from common import APP_URL as URL
from common import OUT, check, finish, wait_until
from playwright.sync_api import sync_playwright

HEADER = "Task,Owner,Deadline,Status,Meeting,Meeting date,Subtasks done,Overdue"


def sign_in(page):
    page.goto(URL)
    page.get_by_placeholder("you@example.com").fill("demo@example.com")
    page.get_by_placeholder("Password").fill("demo1234")
    page.locator("form:has(input[placeholder='you@example.com']) button[type=submit]").click()
    page.locator("button[aria-label='Export to spreadsheet']").first.wait_for(timeout=20000)


def download(page):
    """Open the options box and download; returns the file's raw bytes."""
    page.locator("button[aria-label='Export to spreadsheet']").first.click()
    time.sleep(0.4)
    with page.expect_download() as d:
        page.get_by_role("button", name="Download").click()
    return open(d.value.path(), "rb").read()


def rows(raw):
    return raw.decode("utf-8-sig").split("\r\n")


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1512, "height": 900}, accept_downloads=True)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    sign_in(pg)
    card_count = lambda: pg.locator('[aria-label="Delete task"]').count()  # noqa: E731
    wait_until(lambda: card_count() > 0)
    cards = card_count()

    raw = download(pg)
    lines = rows(raw)
    check("the file starts with a byte-order mark and uses CRLF line endings",
          raw[:3] == b"\xef\xbb\xbf" and b"\r\n" in raw)
    check("the header names every column", lines[0] == HEADER, lines[0])
    check("every task on the board is exported", len(lines) - 1 == cards and cards > 0, f"{len(lines) - 1} rows, {cards} cards")

    pg.locator("button[title='Filter by owner']").first.click()
    time.sleep(0.4)
    pg.get_by_role("option", name="Daniel").first.click()
    pg.keyboard.press("Escape")
    time.sleep(0.5)
    shown = pg.locator('[aria-label="Delete task"]').count()
    filtered = rows(download(pg))[1:]
    owners = {r.split(",")[1] for r in filtered}
    check("with the owner filter on, only the tasks shown are exported",
          len(filtered) == shown and owners == {"Daniel"}, f"{len(filtered)} rows, owners {sorted(owners)}")
    pg.screenshot(path=f"{OUT}/export_desk.png")
    check("no page errors", not errs, "; ".join(errs[:2]))
    ctx.close()

    ph = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    sign_in(ph)
    check("on a phone the page does not scroll sideways",
          not ph.evaluate("document.documentElement.scrollWidth > innerWidth"))
    ph.screenshot(path=f"{OUT}/export_phone.png")
    b.close()

finish()
