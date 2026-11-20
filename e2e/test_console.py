"""End-to-end test of the web console: browser -> static site -> API -> bench.

Needs the API on :8000 and the site on :5500 (CI starts both):
    pytest e2e --browser chromium
"""

import os
import re

from playwright.sync_api import Page, expect

SITE = os.environ.get("SITE_URL", "http://localhost:5500/")


def run_release(page: Page, release: str) -> None:
    page.check(f"input[value='{release}']", force=True)
    page.click("#run-btn")
    expect(page.locator("#run-info")).to_contain_text(f"Release {release}:", timeout=120_000)


def test_defects_found_then_fixes_verified(page: Page):
    page.goto(SITE)
    expect(page.locator("#api-status")).to_have_class(re.compile("online"), timeout=60_000)
    page.click("#reset-btn")
    expect(page.locator("#issue-table")).to_contain_text("No issues yet")

    run_release(page, "1.3.0")
    expect(page.locator("#run-info")).to_have_text("Release 1.3.0: 8 passed, 3 failed")
    expect(page.locator("#procedures .badge.fail")).to_have_count(3)
    expect(page.locator("#issue-table .badge.open")).to_have_count(3)
    expect(page.locator("#detail")).to_be_visible()  # first failed procedure opens with charts
    expect(page.locator("#charts canvas")).to_have_count(5)

    page.locator("#issue-table tbody tr", has_text="re-engage").click()
    expect(page.locator("#issue-report")).to_contain_text("Steps to reproduce")
    expect(page.locator("#issue-report")).to_contain_text("high (safety)")

    run_release(page, "1.4.0")
    expect(page.locator("#run-info")).to_have_text("Release 1.4.0: 11 passed, 0 failed")
    expect(page.locator("#issue-table .badge.verified")).to_have_count(3)


def test_guidance_section_shows_real_track(page: Page):
    page.goto(SITE)
    expect(page.locator("#guidance-sub")).to_contain_text("IJsselmeer", timeout=60_000)
    expect(page.locator("#guidance-stats")).to_contain_text("95th pct |XTE|")
