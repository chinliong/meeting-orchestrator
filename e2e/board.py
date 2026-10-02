"""Boards as a guest: extraction, owner filter, undo per board, a slow extraction and a recording
finishing after a board switch, drag to Done, and carrying guest boards into a new account."""
import time

from common import APP_URL as URL
from common import check, finish, silent_wav
from playwright.sync_api import expect, sync_playwright


def vis(page, sel):
    return page.locator(sel + " >> visible=true").first

def cards(page):
    return page.locator('[aria-label="Delete task"]').count()

def wait_cards(page, n, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if cards(page) == n: return True
        time.sleep(0.25)
    return False

def heading(page):
    return page.locator("main h2").first.inner_text()

def new_board(page, name, first=False):
    if first: page.get_by_text("Create your first project").click()
    else: vis(page, "button:has-text('New project')").click()
    page.get_by_placeholder("e.g. SAP S/4HANA Go-Live Programme").fill(name)
    page.get_by_role("button", name="Create project").click()
    expect(page.locator("main h2").first).to_have_text(name)

def switch(page, name):
    vis(page, "header button:has(span.truncate)").click()
    page.locator("div.z-40 li button", has_text=name).first.click()
    expect(page.locator("main h2").first).to_have_text(name)
    time.sleep(1)  # let the board's tasks load

def paste(page, text):
    page.get_by_placeholder("Paste the raw meeting transcript here.").fill(text)
    page.get_by_role("button", name="Parse transcript").click()

def filter_pill(page, owner):
    """Choose an owner in the owner filter (now a dropdown with checkboxes)."""
    class _Choice:
        def click(self_inner):
            page.locator("div.flex-wrap:has(> span:text-is('Filter')) button[aria-haspopup='listbox']").first.click()
            time.sleep(0.3)
            page.locator("[role=listbox][aria-label='Filter by owner'] button", has_text=owner).first.click()
            time.sleep(0.2)
            page.keyboard.press("Escape")
            time.sleep(0.3)
    return _Choice()

def form_error(page):
    loc = page.locator("form p.text-rose-200")
    return loc.inner_text() if loc.count() else ""

def delete_first_card(page):
    card = page.locator("div.group:has([aria-label='Delete task'])").first
    card.hover()
    card.locator('[aria-label="Delete task"]').click()  # a real click: fails if anything covers the button

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(URL)
    page.get_by_role("button", name="Continue as guest").click()

    # --- baseline: create a board and extract tasks (main functionality) ---
    new_board(page, "Board A", first=True)
    paste(page, "normal meeting")
    check("A: transcript extraction adds 2 tasks", wait_cards(page, 2))

    # --- Fix 2: owner filter ---
    filter_pill(page, "Daniel").click()
    check("A: filtering by Daniel shows 1 task", wait_cards(page, 1))
    new_board(page, "Board B")
    paste(page, "UNASSIGNED meeting")
    check("B: filter from A does not hide B's 3 unassigned tasks", wait_cards(page, 3), f"cards={cards(page)}")
    switch(page, "Board A")
    check("A: filter was reset on switching back (2 tasks shown)", wait_cards(page, 2), f"cards={cards(page)}")
    filter_pill(page, "Daniel").click()
    wait_cards(page, 1)
    delete_first_card(page)
    check("A: after deleting Daniel's only task, Priya's task shows (filter cleared)", wait_cards(page, 1), f"cards={cards(page)}")
    vis(page, "button[aria-label='Undo']").click()
    check("A: undo restores the deleted task on the same board", wait_cards(page, 2), f"cards={cards(page)}")

    # --- Fix 1: a slow extraction on A must not replace B's board ---
    paste(page, "SLOW normal meeting")
    time.sleep(0.5)
    switch(page, "Board B")
    time.sleep(7)
    check("B: still shows B's 3 tasks after A's extraction finished", heading(page) == "Board B" and cards(page) == 3,
          f"heading={heading(page)} cards={cards(page)}")
    check("B: no stray Daniel task on B", page.locator("main", has_text="Finish APAC mapping").count() == 0)
    # Adding a task on B only works if B's own share token is active (guests have no account).
    vis(page, "button:has-text('Add task')").click()
    page.get_by_placeholder("What needs to be done?").fill("Manual task on B")
    page.locator("form button[type=submit]:has-text('Add task')").click()
    check("B: adding a task works (correct board token active)", wait_cards(page, 4), f"cards={cards(page)}")
    switch(page, "Board A")
    check("A: the slow extraction's tasks landed on A (4 tasks)", wait_cards(page, 4), f"cards={cards(page)}")

    # --- Fix 4: undo history is per board ---
    delete_first_card(page)
    wait_cards(page, 3)
    undo = vis(page, "button[aria-label='Undo']")
    end = time.time() + 5
    while time.time() < end and not undo.is_enabled(): time.sleep(0.2)
    check("A: undo is enabled after a delete", undo.is_enabled())
    switch(page, "Board B")
    t0 = time.time()
    while time.time() - t0 < 3 and vis(page, "button[aria-label='Undo']").is_enabled(): time.sleep(0.05)
    check("B: undo is disabled after switching boards", not vis(page, "button[aria-label='Undo']").is_enabled(), f"after {time.time()-t0:.2f}s")
    page.keyboard.press("Control+z"); time.sleep(1)
    check("B: Ctrl+Z on B does nothing to B (still 4 tasks, no error)", cards(page) == 4 and page.locator("main p.bg-red-50").count() == 0)

    # --- Fix 3: audio upload polling survives a board switch ---
    switch(page, "Board A")
    before = cards(page)
    page.get_by_role("button", name="Audio / video").click()
    page.locator("input[type=file][accept='audio/*,video/*']").set_input_files(silent_wav())
    page.get_by_role("button", name="Transcribe & parse").click()
    time.sleep(1)
    switch(page, "Board B")
    end = time.time() + 30
    while time.time() < end and page.get_by_role("button", name="Transcribing & parsing...").count():
        time.sleep(0.5)
    err = form_error(page)
    check("audio: polling finished without an error after switching boards", err == "" and cards(page) == 4, f"error={err!r} cards={cards(page)}")
    switch(page, "Board A")
    check("audio: the recording's tasks landed on A", wait_cards(page, before + 2), f"cards={cards(page)} expected={before+2}")

    # --- regression: status change by drag, and undo of it ---
    todo_col = page.locator("h2:text-is('To Do')").locator("xpath=../..")
    done_col = page.locator("h2:text-is('Done')").locator("xpath=../..")
    n_done = done_col.locator('[aria-label="Delete task"]').count()
    page.evaluate("""([src, dst]) => {
      const dt = new DataTransfer();
      src.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
      dst.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true}));
      dst.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
    }""", [todo_col.locator("[draggable=true]").first.element_handle(), done_col.element_handle()])
    time.sleep(1)
    check("drag: card moves to Done", done_col.locator('[aria-label="Delete task"]').count() == n_done + 1)
    page.reload()
    page.wait_for_selector("main h2")
    time.sleep(1.5)
    switch(page, "Board A")
    time.sleep(1)
    done_col = page.locator("h2:text-is('Done')").locator("xpath=../..")
    check("drag: status change persisted after reload", done_col.locator('[aria-label="Delete task"]').count() == n_done + 1)

    # --- regression: sign-up claims guest boards; sign out / sign in ---
    vis(page, "button:has-text('Sign in / Save')").click()
    page.get_by_role("button", name="Create account").first.click()
    page.get_by_placeholder("you@example.com").fill("e2e@example.com")
    page.get_by_placeholder("Password").fill("pw123456")
    page.locator("form:has(input[placeholder='you@example.com']) button[type=submit]").click()
    time.sleep(2)
    vis(page, "header button:has(span.truncate)").click()
    names = page.locator("div.z-40 li button").all_inner_texts()
    page.keyboard.press("Escape")
    check("signup: both guest boards carried into the account", any("Board A" in n for n in names) and any("Board B" in n for n in names), str(names))
    vis(page, "button:has-text('Sign out')").click()
    page.get_by_placeholder("you@example.com").fill("e2e@example.com")
    page.get_by_placeholder("Password").fill("pw123456")
    page.locator("form:has(input[placeholder='you@example.com']) button[type=submit]").click()
    time.sleep(2)
    check("login: boards load for the account", cards(page) > 0 and page.locator("main p.bg-red-50").count() == 0, f"cards={cards(page)}")

    check("no uncaught page errors", not errors, "; ".join(errors)[:300])
    browser.close()

finish()
