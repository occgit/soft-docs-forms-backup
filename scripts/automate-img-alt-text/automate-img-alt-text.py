import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

BASE_URL = "https://oaklandcccentral.etrieve.cloud"
FORM_SETTINGS_URL_TEMPLATE = BASE_URL + "/Index#/settings/forms/{form_id}/"

DEFAULT_STATE_FILE = "state/softdocs_state.json"
DEFAULT_MARKDOWN_FILE = "scripts/automate-img-alt-text/missing-img-alt-list-sm.md"

PAGE_SETTLE_WAIT_MS = 1500
PAGE_LOAD_TIMEOUT_MS = 3000
POST_NAV_WAIT_MS = 400
STATE_TIMEOUT = 5000



@dataclass
class PublishProbeResult:
    is_authenticated: bool
    final_url: str
    has_publish: bool
    has_unpublish: bool
    reasons: list[str]


def read_form_ids_from_markdown(markdown_file: Path) -> list[int]:
    """
    Read form IDs from a markdown file.

    This is intentionally flexible and will pull standalone integers
    from bullet lists, tables, or plain text.
    """
    content = markdown_file.read_text(encoding="utf-8")
    matches = re.findall(r"\b\d+\b", content)

    seen = set()
    form_ids: list[int] = []

    for match in matches:
        form_id = int(match)
        if form_id not in seen:
            seen.add(form_id)
            form_ids.append(form_id)

    return form_ids


def create_browser_context(
    playwright: Playwright,
    state_file: Path,
    headless: bool,
) -> tuple[Browser, BrowserContext]:
    """
    Launch browser and load persisted session state.
    """
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context(
        storage_state=str(state_file),
    )
    return browser, context


def wait_for_page_to_settle(page: Page, wait_ms: int = PAGE_SETTLE_WAIT_MS) -> None:
    """
    Give the SPA time to finish async UI updates.
    """
    page.wait_for_timeout(wait_ms)


def page_probe_publish(page: Page) -> PublishProbeResult:
    """
    Check whether the page looks authenticated and whether the publish toggle
    can be identified.
    """
    final_url = page.url
    final_url_lower = final_url.lower()
    reasons: list[str] = []

    is_login_redirect = "login" in final_url_lower or "oauth" in final_url_lower
    if is_login_redirect:
        reasons.append("redirected to login flow")

    has_publish = False
    has_unpublish = False
    found_toggle = False

    try:
        toggle_button = page.locator("button.pendo-classic-fb-publish-toggle").first
        if toggle_button.count() > 0:
            found_toggle = True
            reasons.append("found publish toggle")

            label_span = toggle_button.locator("span[aria-label]").first
            aria_label = (label_span.get_attribute("aria-label") or "").strip().lower()
            visible_text = label_span.inner_text().strip().lower()

            if "un-publish" in aria_label or visible_text == "un-publish":
                has_unpublish = True
                reasons.append("found Un-Publish")
            elif aria_label.endswith("publish") or visible_text == "publish":
                has_publish = True
                reasons.append("found Publish")

    except Exception:
        pass

    is_authenticated = (not is_login_redirect) and found_toggle

    return PublishProbeResult(
        is_authenticated=is_authenticated,
        final_url=final_url,
        has_publish=has_publish,
        has_unpublish=has_unpublish,
        reasons=reasons,
    )


def wait_for_publish_actions_ready(page: Page) -> None:
    """
    Wait for the publish toggle button to appear.
    """
    page.locator("button.pendo-classic-fb-publish-toggle").first.wait_for(
        state="visible",
        timeout=STATE_TIMEOUT,
    )


def detect_publish_state(page: Page) -> Optional[str]:
    """
    Returns:
      - 'unpublish' if the form is currently published
      - 'publish' if the form is currently unpublished
      - None if the state cannot be determined
    """
    toggle_button = page.locator("button.pendo-classic-fb-publish-toggle").first
    toggle_button.wait_for(state="visible", timeout=STATE_TIMEOUT)

    label_span = toggle_button.locator("span[aria-label]").first
    aria_label = (label_span.get_attribute("aria-label") or "").strip().lower()
    visible_text = label_span.inner_text().strip().lower()

    if "un-publish" in aria_label or visible_text == "un-publish":
        return "unpublish"

    if aria_label.endswith("publish") or visible_text == "publish":
        return "publish"

    return None


def open_form_settings_page(page: Page, form_id: int) -> PublishProbeResult:
    """
    Navigate to a form's settings page and return probe results.
    """
    url = FORM_SETTINGS_URL_TEMPLATE.format(form_id=form_id)
    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
    page.wait_for_timeout(POST_NAV_WAIT_MS)
    wait_for_publish_actions_ready(page)
    wait_for_page_to_settle(page)
    return page_probe_publish(page)


def fail_fast_auth_check(page: Page, form_id: int) -> None:
    """
    Validate the saved session before processing the full list.
    """
    result = open_form_settings_page(page, form_id)

    print(f"Fail-fast auth check for form {form_id}")
    print(f"Final URL: {result.final_url}")
    for reason in result.reasons:
        print(f"  - {reason}")

    if not result.is_authenticated:
        raise RuntimeError(
            "Auth check failed. Session expired or invalid. "
            "Run save-session.py to refresh state."
        )


def click_unpublish_and_wait(page: Page) -> None:
    """
    Click the publish toggle when it is showing Un-Publish, then wait for the
    UI to flip to Publish.
    """
    toggle_button = page.locator("button.pendo-classic-fb-publish-toggle").first
    toggle_button.click(timeout=STATE_TIMEOUT)

    try:
        page.wait_for_function(
            """
            () => {
                const btn = document.querySelector(
                    'button.pendo-classic-fb-publish-toggle span'
                );
                if (!btn) return false;
                return btn.innerText.trim().toLowerCase() === 'publish';
            }
            """,
            timeout=5000,
        )
    except Exception:
        print("  - warning: state did not visibly change after click")

def click_builder_sidebar(page: Page) -> None:
    builder_link = page.locator('a[data-cy="builder"]').first
    builder_link.wait_for(state="visible", timeout=STATE_TIMEOUT)
    builder_link.click(timeout=STATE_TIMEOUT)

    page.wait_for_timeout(1500)

    if "/builder" not in page.url:
        print(f"  - warning: did not land on builder page, current URL: {page.url}")

def save_manifest(manifest_path: Path, manifest: dict[str, Any]) -> None:
    """
    Write manifest JSON.
    """
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def scan_forms(
    page: Page,
    form_ids: list[int],
    manifest: dict[str, Any],
) -> None:
    """
    Process each form:
    - open settings page
    - detect publish state
    - click Un-Publish when present
    - log when already unpublished
    """
    results: list[dict[str, Any]] = manifest["results"]
    total_forms = len(form_ids)

    for index, form_id in enumerate(form_ids, start=1):
        print(f"\n[{index}/{total_forms}] Processing form ID {form_id}...")

        entry: dict[str, Any] = {
            "form_id": form_id,
            "status": "",
            "publish_state_before": None,
            "publish_state_after": None,
            "error": None,
        }

        try:
            probe = open_form_settings_page(page, form_id)

            if "login" in probe.final_url.lower() or "oauth" in probe.final_url.lower():
                raise RuntimeError("Session expired during scan")

            state = detect_publish_state(page)
            entry["publish_state_before"] = state

            if state == "unpublish":
                print("  - action: clicking Un-Publish")
                click_unpublish_and_wait(page)

                final_state = detect_publish_state(page)
                entry["publish_state_after"] = final_state
                print(f"  - result: final state is {final_state}")

                if final_state == "publish":
                    print("  - action: clicking Builder in sidebar")
                    click_builder_sidebar(page)

                    print("  - action: clicking first builder row")
                    click_first_builder_row(page)

                    print("  - action: clicking header logo")
                    click_header_logo(page)
                    # after second logo click
                    page.wait_for_timeout(1000)  # let UI settle slightly

                    input("Edit properties manually, save, then press ENTER...")

                    click_general_settings(page)

                    print("  - waiting for General Settings to load")
                    wait_for_publish_actions_ready(page)

                    state_after_return = detect_publish_state(page)

                    if state_after_return == "publish":
                        print("  - action: clicking Publish")
                        click_publish_and_wait(page)
                    else:
                        print("  - action: already published (Un-Publish visible)")

                    entry["status"] = "clicked_unpublish_builder_row"
                else:
                    entry["status"] = "clicked_unpublish"

            elif state == "publish":
                print("  - action: already unpublished (Publish visible)")
                entry["publish_state_after"] = state
                entry["status"] = "already_unpublished"

            else:
                print("  - state: could not determine")
                entry["publish_state_after"] = state
                entry["status"] = "unknown"

            results.append(entry)

        except Exception as exc:
            entry["status"] = "failed"
            entry["error"] = str(exc).strip()
            results.append(entry)

            print(f"\n  - FAILED on form {form_id}")
            print(f"  - error: {entry['error']}")
            print(f"  - current URL: {page.url}")

            input("Resolve the issue in the browser, then press ENTER to continue...")

def click_first_builder_row(page: Page) -> None:
    """
    Wait for the Builder iframe to load, then click the first row label
    inside the builder content.
    """
    page.wait_for_timeout(1000)

    # Wait for the iframe itself to be present on the builder page
    builder_iframe = page.locator("#templateBuilderiFrame").first
    builder_iframe.wait_for(state="visible", timeout=STATE_TIMEOUT)

    # Work inside the iframe DOM
    builder_frame = page.frame_locator("#templateBuilderiFrame")

    # Wait for the content area inside the iframe
    content = builder_frame.locator("#content")
    content.wait_for(state="visible", timeout=STATE_TIMEOUT)

    # Then target the row inside that iframe content
    row_label = builder_frame.locator("#callRowLabel1")
    row_label.wait_for(state="visible", timeout=STATE_TIMEOUT)
    row_label.click(timeout=STATE_TIMEOUT)

    page.wait_for_timeout(800)

def click_header_logo(page: Page) -> None:
    """
    Click the header logo element twice (select + activate).
    """
    builder_frame = page.frame_locator("#templateBuilderiFrame")

    logo_img = builder_frame.locator(
        'img[src*="thumbnail_horizontal.png"]'
    ).first

    logo_img.wait_for(state="visible", timeout=STATE_TIMEOUT)

    # Click parent container (more reliable)
    logo_container = logo_img.locator("..")

    print("  - clicking header logo (select)")
    logo_container.click(timeout=STATE_TIMEOUT)

    # Brief pause before second click
    page.wait_for_timeout(400)

    print("  - clicking header logo (activate)")
    logo_container.click(timeout=STATE_TIMEOUT)

    page.wait_for_timeout(800)

def click_general_settings(page: Page) -> None:
    """
    Click the General Settings link in the left sidebar.
    """
    general_settings_link = page.get_by_role("link", name="General Settings").first
    general_settings_link.wait_for(state="visible", timeout=STATE_TIMEOUT)
    general_settings_link.click(timeout=STATE_TIMEOUT)

    page.wait_for_timeout(1500)

    if "/settings/forms/" not in page.url:
        print(f"  - warning: unexpected URL after General Settings click: {page.url}")

def click_publish_and_wait(page: Page) -> None:
    """
    Click the publish toggle when it is showing Publish, then wait for the
    UI to flip to Un-Publish.
    """
    toggle_button = page.locator("button.pendo-classic-fb-publish-toggle").first
    toggle_button.wait_for(state="visible", timeout=STATE_TIMEOUT)

    toggle_button.click(timeout=STATE_TIMEOUT)

    try:
        page.wait_for_function(
            """
            () => {
                const btn = document.querySelector(
                    'button.pendo-classic-fb-publish-toggle span'
                );
                if (!btn) return false;
                return btn.innerText.trim().toLowerCase().includes('un-publish');
            }
            """,
            timeout=5000,
        )
    except Exception:
        print("  - warning: state did not visibly change after Publish click")

def main() -> None:
    """
    Validate inputs, initialize browser/session, run scan, and write manifest.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    parser.add_argument("--markdown-file", default=DEFAULT_MARKDOWN_FILE)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    state_file = Path(args.state_file).resolve()
    if not state_file.exists():
        print(f"ERROR: Storage state file not found: {state_file}")
        sys.exit(99)

    markdown_file = Path(args.markdown_file).resolve()
    if not markdown_file.exists():
        print(f"ERROR: Markdown file not found: {markdown_file}")
        sys.exit(98)

    form_ids = read_form_ids_from_markdown(markdown_file)
    if not form_ids:
        print("ERROR: No form IDs found in markdown file.")
        sys.exit(97)

    manifest_path = (
        markdown_file.parent
        / f"publish-scan-{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.json"
    )

    manifest: dict[str, Any] = {
        "started_at": datetime.now().isoformat(),
        "state_file": str(state_file),
        "markdown_file": str(markdown_file),
        "form_ids": form_ids,
        "headless": args.headless,
        "results": [],
    }

    browser: Browser | None = None

    try:
        with sync_playwright() as playwright:
            browser, context = create_browser_context(
                playwright=playwright,
                state_file=state_file,
                headless=args.headless,
            )
            page = context.new_page()

            first_form_id = form_ids[0]
            fail_fast_auth_check(page, form_id=first_form_id)

            scan_forms(
                page=page,
                form_ids=form_ids,
                manifest=manifest,
            )

            manifest["finished_at"] = datetime.now().isoformat()
            save_manifest(manifest_path, manifest)

            print("\nDone.")
            print(f"Manifest: {manifest_path}")

            browser.close()
            sys.exit(0)

    except Exception as exc:
        manifest["finished_at"] = datetime.now().isoformat()
        manifest["fatal_error"] = str(exc).strip()

        try:
            save_manifest(manifest_path, manifest)
        except Exception:
            pass

        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass

        print(f"ERROR: {manifest['fatal_error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()