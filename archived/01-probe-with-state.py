import argparse
import sys
from pathlib import Path

from playwright.sync_api import Page, Response, TimeoutError as PlaywrightTimeoutError, sync_playwright


# URL for probing a specific form's file page
TEST_URL_TEMPLATE = "https://oaklandcccentral.etrieve.cloud/Index#/settings/forms/{form_id}/files"


def page_looks_authenticated(page: Page) -> tuple[bool, list[str], list[str]]:
    """
    Authentication check.

    Signals:
    - Negative: login/unauthorized indicators in URL or content
    - Positive: expected UI elements on authenticated pages

    Returns:
        (is_authenticated, negative_signals, positive_signals)
    """
    url = page.url.lower()
    content = page.content().lower()

    negative_signals: list[str] = []
    positive_signals: list[str] = []

    # Common indicators that the session is not authenticated
    negative_checks = [
        ("final URL contains 'login'", "login" in url),
        ("page content contains 'sign in'", "sign in" in content),
        ("page content contains 'log in'", "log in" in content),
        ("page content contains 'unauthorized'", "unauthorized" in content),
        ("page content contains 'forbidden'", "forbidden" in content),
        ("page content contains 'access denied'", "access denied" in content),
    ]

    for label, matched in negative_checks:
        if matched:
            negative_signals.append(label)

    try:
        # Expected signals on a valid authenticated form page
        if "settings/forms" in url:
            positive_signals.append("URL contains settings/forms")
        if page.locator("text=Files").count() > 0:
            positive_signals.append("found Files text")
        if page.locator("text=Edit").count() > 0:
            positive_signals.append("found Edit text")
        if page.locator("table tbody tr").count() > 0:
            positive_signals.append("found table rows")
    except Exception as exc:
        # Selector failures often indicate page did not load as expected
        negative_signals.append(f"selector checks failed: {exc}")

    authenticated = len(negative_signals) == 0 and len(positive_signals) > 0
    return authenticated, negative_signals, positive_signals


def debug_selectors(page: Page) -> None:
    """
    Prints counts for a set of common selectors.

    Quickly understanding what the DOM contains
    when debugging selector issues.
    """
    checks = {
        "body": "body",
        "files_text": "text=Files",
        "edit_text": "text=Edit",
        "download_text": "text=Download",
        "table_rows": "table tbody tr",
        "buttons": "button",
        "anchors": "a",
        "inputs": "input",
    }

    print("\n=== SELECTOR CHECKS ===")
    for label, selector in checks.items():
        try:
            count = page.locator(selector).count()
            print(f"{label}: {count}")
        except Exception as exc:
            print(f"{label}: ERROR -> {exc}")
    print("=== END SELECTOR CHECKS ===\n")


def get_body_text_sample(page: Page, max_chars: int = 1500) -> str:
    """
    Truncated sample of page body text.

    Helps quickly inspect page content without dumping full HTML.
    """
    try:
        body_text = page.locator("body").inner_text(timeout=5000)
        body_text_clean = " ".join(body_text.split())
        return body_text_clean[:max_chars]
    except Exception as exc:
        return f"[unable to read body text: {exc}]"


def save_debug_artifacts(page: Page, output_dir: Path, prefix: str) -> None:
    """
    Saves page HTML for inspection.

    Output is written to: <output_dir>/<prefix>.html
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / f"{prefix}.html"

    html_path.write_text(page.content(), encoding="utf-8")

    print(f"Saved HTML: {html_path.resolve()}")


def run_probe(storage_state_path: Path, form_id: int, headless: bool) -> int:
    """
    - Loads Playwright storage state (cookies/session)
    - Navigates to a form page
    - Collects diagnostics (auth signals, requests, console, DOM)

    Returns:
        0 if authenticated
        1 if not authenticated
        2 on navigation timeout
    """
    if not storage_state_path.exists():
        raise RuntimeError(f"Storage state file not found: {storage_state_path}")

    test_url = TEST_URL_TEMPLATE.format(form_id=form_id)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)

        # Load saved session state into browser context
        context = browser.new_context(storage_state=str(storage_state_path))
        page = context.new_page()

        console_messages: list[str] = []
        request_failures: list[str] = []
        seen_requests: list[str] = []

        # Capture console output from the page
        def on_console(msg) -> None:
            console_messages.append(f"[{msg.type}] {msg.text}")

        # Capture failed network requests
        def on_request_failed(request) -> None:
            failure = request.failure
            failure_text = str(failure) if failure else "unknown failure"
            request_failures.append(f"{request.method} {request.url} -> {failure_text}")

        # Capture outgoing requests (filtered to etrieve domain)
        def on_request(request) -> None:
            if "etrieve" not in request.url.lower():
                return

            req_headers = request.headers
            auth_header = req_headers.get("authorization", "")
            cookie_value = req_headers.get("cookie", "")

            seen_requests.append(
                f"{request.method} {request.url} | "
                f"auth={'yes' if bool(auth_header) else 'no'} | "
                f"cookie={'yes' if bool(cookie_value) else 'no'}"
            )

        # Attach event listeners before navigation
        page.on("console", on_console)
        page.on("requestfailed", on_request_failed)
        page.on("request", on_request)

        output_dir = Path("state").resolve()
        prefix = "probe_storage_state"

        try:
            # Navigate to target form page
            response: Response | None = page.goto(
                test_url,
                wait_until="domcontentloaded",
                timeout=30000,
            )

            # Allow additional async requests/UI rendering
            page.wait_for_timeout(5000)

            print(f"Requested URL: {test_url}")
            print(f"Final URL: {page.url}")

            try:
                print(f"Page title: {page.title()}")
            except Exception as exc:
                print(f"Page title unavailable: {exc}")

            # Basic response diagnostics
            if response is None:
                print("Main response: None")
            else:
                print(f"Main response status: {response.status}")
                print(f"Main response OK: {response.ok}")

            # Inspect cookies loaded from storage state
            loaded_cookies = context.cookies()
            print(f"Loaded cookies in browser context: {len(loaded_cookies)}")
            for cookie in loaded_cookies[:10]:
                cookie_name = cookie.get("name", "<missing-name>")
                cookie_domain = cookie.get("domain", "<missing-domain>")
                print(f"  COOKIE -> {cookie_name} @ {cookie_domain}")

            # Evaluate authentication status
            authenticated, negative_signals, positive_signals = page_looks_authenticated(page)

            print("\n=== AUTH SIGNALS ===")
            print("Negative signals:")
            if negative_signals:
                for signal in negative_signals:
                    print(f"  - {signal}")
            else:
                print("  - none")

            print("Positive signals:")
            if positive_signals:
                for signal in positive_signals:
                    print(f"  - {signal}")
            else:
                print("  - none")
            print("=== END AUTH SIGNALS ===\n")

            print(f"Looks authenticated: {authenticated}")

            # Print sample of page text for quick inspection
            body_text_sample = get_body_text_sample(page)
            print("\n=== PAGE TEXT SAMPLE ===")
            print(body_text_sample)
            print("=== END PAGE TEXT SAMPLE ===\n")

            # Dump selector counts
            debug_selectors(page)

            # Print captured requests
            print("=== REQUEST SAMPLE ===")
            if seen_requests:
                for line in seen_requests[:25]:
                    print(line)
            else:
                print("No matching etrieve requests captured.")
            print("=== END REQUEST SAMPLE ===\n")

            # Print failed requests
            print("=== FAILED REQUESTS ===")
            if request_failures:
                for line in request_failures[:25]:
                    print(line)
            else:
                print("No failed requests captured.")
            print("=== END FAILED REQUESTS ===\n")

            # Print browser console messages
            print("=== CONSOLE MESSAGES ===")
            if console_messages:
                for line in console_messages[:25]:
                    print(line)
            else:
                print("No console messages captured.")
            print("=== END CONSOLE MESSAGES ===\n")

            # Persist HTML snapshot for debugging
            save_debug_artifacts(page, output_dir, prefix)

            browser.close()
            return 0 if authenticated else 1

        except PlaywrightTimeoutError:
            print("Timed out loading the page.")
            try:
                save_debug_artifacts(page, output_dir, f"{prefix}_timeout")
            except Exception as exc:
                print(f"Could not save timeout artifacts: {exc}")
            browser.close()
            return 2


def main() -> None:
    """
    Arguments:
    - --form-id: target form ID to probe
    - --state-file: path to saved Playwright storage state
    - --headless: run browser without UI
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--form-id", type=int, default=1)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--state-file", default="state/softdocs_state.json")
    args = parser.parse_args()

    try:
        exit_code = run_probe(
            storage_state_path=Path(args.state_file).resolve(),
            form_id=args.form_id,
            headless=args.headless,
        )
        sys.exit(exit_code)
    except Exception as exc:
        print(f"ERROR: {exc}")
        sys.exit(99)


if __name__ == "__main__":
    main()
