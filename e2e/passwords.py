"""The 8-character rule for new passwords: sign-up and password change refuse shorter ones, and
sign-in does not check the length, so older accounts still sign in."""
import time

from common import APP_URL as URL
from common import OUT, check, finish
from playwright.sync_api import sync_playwright

email = f"pwrule{int(time.time())}@example.com"
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(URL); pg.get_by_role("button", name="Create account").first.click()
    pw = pg.get_by_placeholder("Password (at least 8 characters)")
    check("sign-up shows the rule", pw.is_visible())
    pg.get_by_placeholder("you@example.com").fill(email); pw.fill("1234567")
    pg.locator("form button[type=submit]").click()
    check("7 characters refused with a message", pg.get_by_text("Password must be at least 8 characters.").is_visible())
    pw.fill("12345678"); pg.locator("form button[type=submit]").click()
    pg.get_by_text("No projects yet").wait_for(timeout=15000)
    check("8 characters accepted, signed in", True)
    pg.get_by_text(email[:12]).first.click()
    pg.get_by_role("button", name="Change", exact=True).click()
    pg.get_by_placeholder("Current password").fill("12345678")
    pg.get_by_placeholder("New password (at least 8 characters)").fill("abc")
    pg.get_by_placeholder("Confirm new password").fill("abc")
    pg.get_by_role("button", name="Update password").click()
    check("short new password refused", pg.get_by_text("Password must be at least 8 characters.").is_visible())
    pg.get_by_placeholder("New password (at least 8 characters)").fill("abcdefgh")
    pg.get_by_placeholder("Confirm new password").fill("abcdefgh")
    pg.get_by_role("button", name="Update password").click()
    check("valid new password saved", pg.get_by_text("Password updated.").wait_for(timeout=10000) is None)
    pg.screenshot(path=f"{OUT}/pw_rule.png")
    # sign-in with a short password is not blocked by the rule (existing accounts)
    pg2 = b.new_page(); pg2.goto(URL)
    pg2.get_by_placeholder("you@example.com").fill("nobody@example.com"); pg2.get_by_placeholder("Password", exact=True).fill("12345")
    pg2.locator("form button[type=submit]").click(); pg2.wait_for_timeout(1500)
    check("sign-in is not checked for length", not pg2.get_by_text("at least 8 characters").is_visible() and pg2.get_by_text("Invalid email or password").is_visible())
    check("no page errors", not errs)
    b.close()
finish()
