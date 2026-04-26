import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Download, Page, Playwright, sync_playwright


# ---------------------------------------
# Softdocs URLs
# ---------------------------------------

BASE_URL = "https://oaklandcccentral.etrieve.cloud"
FORM_FILES_URL_TEMPLATE = BASE_URL + "/Index#/settings/forms/{form_id}/files"


# ---------------------------------------
# Chrome / Playwright settings
# ---------------------------------------

DEFAULT_CDP_URL = "http://127.0.0.1:9222"
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROME_USER_DATA_DIR = Path.home() / "AppData/Local/ChromePlaywrightSoftdocs"


# ---------------------------------------
# Script defaults
# ---------------------------------------

DEFAULT_MIN_ID = 1
DEFAULT_MAX_ID = 10
DEFAULT_OUTPUT_ROOT = "backups"
FAILED_FORM_IDS_CSV_DEFAULT = ""


# ---------------------------------------
# Timing settings
# ---------------------------------------

PAGE_SETTLE_WAIT_MS = 1500
PAGE_LOAD_TIMEOUT_MS = 5000
POST_NAV_WAIT_MS = 500
DOWNLOAD_TIMEOUT_MS = 4500
CHROME_STARTUP_WAIT_SECONDS = 2.5


@dataclass
class ProbeResult:
    """Stores what the script found after opening a form files page."""

    is_authenticated: bool
    final_url: str
    has_files_text: bool
    has_edit_text: bool
    reasons: list[str]


def now_timestamp() -> str:
    """Create a timestamp used for the backup folder name."""

    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def slugify_windows_safe(name: str) -> str:
    """Clean text so it can safely be used as a Windows folder name."""

    value = name.strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = value.rstrip(". ")

    if not value:
        value = "unnamed-form"

    return value


def ensure_directory(path: Path) -> None:
    """Create a folder if it does not already exist."""

    path.mkdir(parents=True, exist_ok=True)


def build_output_paths(output_root: Path) -> tuple[Path, Path, Path]:
    """Create the main run folder, zip folder, and manifest file path."""

    run_root = output_root / now_timestamp()
    zip_root = run_root / "zips"
    manifest_path = run_root / "manifest.json"

    return run_root, zip_root, manifest_path


def save_manifest(manifest_path: Path, manifest: dict[str, Any]) -> None:
    """Write the manifest file that records what happened during the run."""

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def launch_chrome() -> subprocess.Popen[bytes]:
    """
    Open Chrome with remote debugging turned on.

    This uses a dedicated Chrome profile, so you can stay logged into Softdocs
    without using the old state/softdocs_state.json file.
    """

    CHROME_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    chrome_args = [
        CHROME_PATH,
        "--remote-debugging-port=9222",
        f"--user-data-dir={CHROME_USER_DATA_DIR}",
        BASE_URL,
    ]

    try:
        process = subprocess.Popen(chrome_args)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Chrome executable not found at: {CHROME_PATH}") from exc

    time.sleep(CHROME_STARTUP_WAIT_SECONDS)

    return process


def attach_to_existing_chrome(
    playwright: Playwright,
    cdp_url: str,
) -> tuple[Browser, BrowserContext]:
    """Attach Playwright to the Chrome window opened by launch_chrome()."""

    browser = playwright.chromium.connect_over_cdp(cdp_url)

    if browser.contexts:
        context = browser.contexts[0]
    else:
        context = browser.new_context()

    return browser, context


def wait_for_page_to_settle(page: Page, wait_ms: int = PAGE_SETTLE_WAIT_MS) -> None:
    """Give the Softdocs single-page app a little extra time to finish rendering."""

    page.wait_for_timeout(wait_ms)


def wait_for_files_actions_ready(page: Page) -> None:
    """Wait until the files toolbar is visible enough to interact with."""

    page.locator(".file-actions .actions").first.wait_for(state="visible", timeout=10000)


def page_probe(page: Page) -> ProbeResult:
    """Check whether the page looks logged in and has the files UI."""

    final_url = page.url
    final_url_lower = final_url.lower()
    reasons: list[str] = []

    is_login_redirect = "login" in final_url_lower or "oauth" in final_url_lower

    if is_login_redirect:
        reasons.append("redirected to login flow")

    has_files_text = False
    has_edit_text = False

    try:
        has_files_text = page.get_by_text("Files", exact=True).count() > 0
    except Exception:
        pass

    try:
        has_edit_text = page.locator("button.pendo-classic-fb-files-edit").count() > 0
    except Exception:
        pass

    if has_files_text:
        reasons.append("found Files text")

    if has_edit_text:
        reasons.append("found Edit button")

    is_authenticated = not is_login_redirect and (has_files_text or has_edit_text)

    return ProbeResult(
        is_authenticated=is_authenticated,
        final_url=final_url,
        has_files_text=has_files_text,
        has_edit_text=has_edit_text,
        reasons=reasons,
    )


def open_form_files_page(page: Page, form_id: int) -> ProbeResult:
    """Open one form's Files page and return what the script found."""

    url = FORM_FILES_URL_TEMPLATE.format(form_id=form_id)

    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
    page.wait_for_timeout(POST_NAV_WAIT_MS)

    wait_for_files_actions_ready(page)
    wait_for_page_to_settle(page)

    return page_probe(page)


def fail_fast_auth_check(page: Page, form_id: int) -> None:
    """Stop early if the Chrome profile is not logged into Softdocs."""

    result = open_form_files_page(page, form_id)

    print(f"Fail-fast auth check for form {form_id}")
    print(f"Final URL: {result.final_url}")

    for reason in result.reasons:
        print(f"  - {reason}")

    if not result.is_authenticated:
        raise RuntimeError(
            "Auth check failed. Chrome opened successfully, but the profile is not logged in."
        )


def is_visible(locator) -> bool:
    """Safely check whether a Playwright locator is visible."""

    try:
        return locator.is_visible()
    except Exception:
        return False


def prepare_files_for_download(page: Page) -> None:
    """
    Put the files page into the right state for downloading.

    The script:
    1. Clicks Edit if needed.
    2. Clicks Select All if available.
    3. Accepts Deselect All as meaning the files are already selected.
    """

    edit_button = page.locator("button.pendo-classic-fb-files-edit").last
    select_all_button = page.locator("#selectAll")
    deselect_all_button = page.locator("#deselectAll")

    if is_visible(edit_button):
        edit_button.click(timeout=10000)
        page.wait_for_timeout(500)

    if is_visible(select_all_button):
        select_all_button.click(timeout=10000)
        page.wait_for_timeout(500)
        return

    if is_visible(deselect_all_button):
        page.wait_for_timeout(300)
        return

    raise RuntimeError("Could not determine file selection state.")


def click_download_icon_and_wait(page: Page) -> Download:
    """Click the download button and wait for the download to start."""

    download_button = page.locator("button.pendo-classic-fb-files-download")
    download_button.wait_for(state="visible", timeout=10000)

    with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as download_info:
        download_button.click(timeout=10000)

    return download_info.value


def save_and_extract_download(
    download: Download,
    zip_root: Path,
    form_output_dir: Path,
) -> tuple[Path, Path]:
    """Save the downloaded zip and extract it into the form backup folder."""

    ensure_directory(zip_root)
    ensure_directory(form_output_dir)

    zip_name = f"{form_output_dir.name}.zip"
    zip_path = zip_root / zip_name
    extracted_dir = form_output_dir / "extracted"

    download.save_as(str(zip_path))

    if extracted_dir.exists():
        shutil.rmtree(extracted_dir)

    ensure_directory(extracted_dir)

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(extracted_dir)

    return zip_path, extracted_dir


def form_output_dir_from_download_name(
    run_root: Path,
    suggested_filename: str,
    form_id: int,
) -> Path:
    """Build a clean folder name using the form ID and downloaded file name."""

    stem = Path(suggested_filename).stem
    safe_name = slugify_windows_safe(stem)
    prefix = f"{form_id:04d}"

    return run_root / f"{prefix}_{safe_name}"


def shorten_error_message(error_text: str) -> str:
    """Trim long Playwright errors so the console and manifest stay readable."""

    lines = error_text.splitlines()
    shortened_lines: list[str] = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue

        if stripped.startswith("==========================="):
            break

        shortened_lines.append(line)

    if shortened_lines:
        return "\n".join(shortened_lines).strip()

    return error_text.strip()


def parse_form_ids_csv(csv_path: Path) -> list[int]:
    """Read form IDs from a CSV file that has a form_id column."""

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path.resolve()}")

    form_ids: list[int] = []

    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        if not reader.fieldnames or "form_id" not in reader.fieldnames:
            raise ValueError("CSV must include 'form_id' column")

        for row_number, row in enumerate(reader, start=2):
            raw_value = (row.get("form_id") or "").strip()

            if not raw_value:
                continue

            try:
                form_id = int(raw_value)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid form_id '{raw_value}' at row {row_number}"
                ) from exc

            form_ids.append(form_id)

    if not form_ids:
        raise ValueError("No form_ids found in CSV")

    return form_ids


def resolve_form_ids(
    min_id: int,
    max_id: int,
    failed_form_ids_csv: str,
) -> list[int]:
    """
    Decide which form IDs to process.

    - If a failed IDs CSV is provided, use that.
    - Otherwise, use the min/max ID range.
    """

    if failed_form_ids_csv:
        return parse_form_ids_csv(Path(failed_form_ids_csv).resolve())

    if min_id > max_id:
        raise ValueError("--min-id cannot be greater than --max-id")

    return list(range(min_id, max_id + 1))


def scan_and_backup_forms(
    page: Page,
    run_root: Path,
    zip_root: Path,
    form_ids: list[int],
    manifest: dict[str, Any],
) -> None:
    """
    Main backup loop.

    For each form ID:
    1. Open the Softdocs files page.
    2. Select all files.
    3. Download the zip.
    4. Extract the zip.
    5. Record success, empty, or failure in the manifest.
    """

    results: list[dict[str, Any]] = manifest["results"]
    total_forms = len(form_ids)

    for index, form_id in enumerate(form_ids, start=1):
        print(f"\n[{index}/{total_forms}] Processing form ID {form_id}...")

        entry: dict[str, Any] = {
            "form_id": form_id,
            "status": "",
            "form_folder": None,
            "error": None,
        }

        try:
            probe = open_form_files_page(page, form_id)

            if "login" in probe.final_url.lower() or "oauth" in probe.final_url.lower():
                raise RuntimeError("Session expired during scan")

            if not (probe.has_files_text and probe.has_edit_text):
                entry["status"] = "empty"
                results.append(entry)
                print("  - skipped: no accessible files UI")
                continue

            prepare_files_for_download(page)

            download = click_download_icon_and_wait(page)
            suggested_filename = download.suggested_filename

            form_dir = form_output_dir_from_download_name(
                run_root=run_root,
                suggested_filename=suggested_filename,
                form_id=form_id,
            )

            zip_path, extracted_dir = save_and_extract_download(
                download=download,
                zip_root=zip_root,
                form_output_dir=form_dir,
            )

            entry["status"] = "success"
            entry["form_folder"] = form_dir.name
            results.append(entry)

            print(f"  - success: {zip_path.name}")
            print(f"  - zip: {zip_path}")
            print(f"  - extracted: {extracted_dir}")

        except Exception as exc:
            entry["status"] = "failed"
            entry["error"] = shorten_error_message(str(exc))
            results.append(entry)

            print(f"  - failed: {entry['error']}")


def main() -> None:
    """
    Script flow:

    1. Read settings from command-line arguments.
    2. Open Chrome with the Softdocs profile.
    3. Attach Playwright to Chrome.
    4. Confirm the profile is logged in.
    5. Download and extract form files.
    6. Save a manifest.
    """

    parser = argparse.ArgumentParser()

    parser.add_argument("--min-id", type=int, default=DEFAULT_MIN_ID)
    parser.add_argument("--max-id", type=int, default=DEFAULT_MAX_ID)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--failed-form-ids-csv", default=FAILED_FORM_IDS_CSV_DEFAULT)
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL)

    args = parser.parse_args()

    form_ids = resolve_form_ids(
        min_id=args.min_id,
        max_id=args.max_id,
        failed_form_ids_csv=args.failed_form_ids_csv,
    )

    if not form_ids:
        print("ERROR: No form IDs found.")
        sys.exit(97)

    output_root = Path(args.output_root).resolve()
    run_root, zip_root, manifest_path = build_output_paths(output_root)

    ensure_directory(run_root)
    ensure_directory(zip_root)

    manifest: dict[str, Any] = {
        "started_at": datetime.now().isoformat(),
        "min_id": args.min_id,
        "max_id": args.max_id,
        "failed_form_ids_csv": str(Path(args.failed_form_ids_csv).resolve())
        if args.failed_form_ids_csv
        else None,
        "form_ids": form_ids,
        "run_root": str(run_root),
        "zip_root": str(zip_root),
        "results": [],
    }

    browser: Browser | None = None
    chrome_process: subprocess.Popen[bytes] | None = None

    try:
        chrome_process = launch_chrome()

        with sync_playwright() as playwright:
            try:
                browser, context = attach_to_existing_chrome(
                    playwright=playwright,
                    cdp_url=args.cdp_url,
                )
            except Exception as exc:
                raise RuntimeError(
                    "Could not attach to Chrome after launch. "
                    "Make sure Chrome supports remote debugging and port 9222 is available."
                ) from exc

            page = context.new_page()

            first_form_id = form_ids[0]
            fail_fast_auth_check(page, form_id=first_form_id)

            scan_and_backup_forms(
                page=page,
                run_root=run_root,
                zip_root=zip_root,
                form_ids=form_ids,
                manifest=manifest,
            )

            manifest["finished_at"] = datetime.now().isoformat()
            save_manifest(manifest_path, manifest)

            print("\nDone.")
            print(f"Manifest: {manifest_path}")
            print(f"Backups:  {run_root}")
            print(f"Zips:     {zip_root}")

            browser.close()
            sys.exit(0)

    except Exception as exc:
        manifest["finished_at"] = datetime.now().isoformat()
        manifest["fatal_error"] = shorten_error_message(str(exc))

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