import argparse
import sys
from pathlib import Path
import time

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


# Base login URL for Softdocs
LOGIN_URL = "https://oaklandcccentral.etrieve.cloud/"

# URL fragments that indicate a successful login
SUCCESS_URL_PARTS = [
    "oaklandcccentral.etrieve.cloud/Index",
    "oaklandcc.etrieve.cloud/central/submissions",
]


def page_looks_logged_in(page: Page) -> tuple[bool, list[str]]:
    """
    Determines whether the user is logged in.

    Checks:
    - Current URL matches known post-login routes
    - Page contains expected text (e.g., 'settings', 'forms')

    Returns:
        (is_logged_in, reasons)
    """
    reasons: list[str] = []
    current_url = page.url.lower()

    # Check if current URL matches any known logged-in routes
    if any(part.lower() in current_url for part in SUCCESS_URL_PARTS):
        reasons.append(f"success URL matched: {page.url}")

    return (len(reasons) > 0, reasons)


def wait_for_login(page: Page, timeout_ms: int) -> bool:
    """
    Waits for the user to manually complete login in the browser.

    Polls the page until either:
    - Login is detected
    - Timeout is reached

    Returns:
        True if login detected, otherwise False
    """
    print("\nBrowser opened.")
    print("Log in manually in the browser window.")
    print("After login completes, the script will save Playwright storage state.")
    print("Waiting for successful login...\n")

    deadline = time.time() + (timeout_ms / 1000)

    # Poll once per second until timeout
    while time.time() < deadline:
        try:
            page.wait_for_timeout(1000)
            logged_in, reasons = page_looks_logged_in(page)
            if logged_in:
                print("Login detected.")
                for reason in reasons:
                    print(f"  - {reason}")
                return True
        except Exception:
            # Ignore transient Playwright errors and continue polling
            pass

    return False


def main() -> None:
    """
    - Parses CLI arguments
    - Launches browser
    - Waits for manual login
    - Saves Playwright storage state to disk
    """
    parser = argparse.ArgumentParser()

    # Output file for Playwright storage state
    parser.add_argument(
        "--output",
        default="state/softdocs_state.json",
        help="Path to save Playwright storage state JSON.",
    )

    # Run browser headless (not recommended for manual login)
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run headless. Usually leave this off for manual login.",
    )

    # Maximum time to wait for login
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="How long to wait for manual login before giving up.",
    )

    args = parser.parse_args()

    # Resolve and ensure output directory exists
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # Launch Chromium browser
        browser = p.chromium.launch(headless=args.headless)

        # Create isolated browser context (stores cookies/session)
        context = browser.new_context()
        page = context.new_page()

        try:
            print(f"Opening login page: {LOGIN_URL}")

            # Navigate to login page
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)

            # Wait for user to complete login
            success = wait_for_login(page, timeout_ms=args.timeout_seconds * 1000)

            if not success:
                print("Timed out waiting for login.")
                print(f"Final URL seen: {page.url}")
                browser.close()
                sys.exit(1)

            # Save session state (cookies, local storage, etc.)
            context.storage_state(path=str(output_path))
            print(f"\nSaved storage state to: {output_path}")

            browser.close()
            sys.exit(0)

        except PlaywrightTimeoutError:
            # Failed to load login page in time
            print("Timed out opening the login page.")
            browser.close()
            sys.exit(2)

        except Exception as exc:
            # Catch-all for unexpected errors
            print(f"ERROR: {exc}")
            browser.close()
            sys.exit(99)


if __name__ == "__main__":
    main()
