import argparse
import csv
import json
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Download,
    Page,
    Playwright,
    sync_playwright,
)

# Usage examples:
# Full scan: iterate sequential form IDs
#   python scripts/02-download-forms.py --max-id 2
#
# Retry only failed IDs from CSV
#   python scripts/02-download-forms.py --failed-form-ids-csv <path>
#   python scripts/02-download-forms.py --failed-form-ids-csv "C:/Users/axvasava/Desktop/repos/soft-docs-forms-backup/backups/2026-04-10_130203/failed_form_ids.csv"


# URL and per-form files page template
BASE_URL = "https://oaklandcccentral.etrieve.cloud"
FORM_FILES_URL_TEMPLATE = BASE_URL + "/Index#/settings/forms/{form_id}/files"

# Defaults for CLI args
DEFAULT_STATE_FILE = "state/softdocs_state.json"
DEFAULT_MAX_ID = 266
DEFAULT_OUTPUT_ROOT = "backups"

# Timing constants
PAGE_SETTLE_WAIT_MS = 1500
PAGE_LOAD_TIMEOUT_MS = 3000
POST_NAV_WAIT_MS = 400
DOWNLOAD_TIMEOUT_MS = 4500
FAILED_FORM_IDS_CSV_DEFAULT = ""


@dataclass
class ProbeResult:
    """
    Result of probing a form page for authentication and UI readiness.
    """
    is_authenticated: bool
    final_url: str
    has_files_text: bool
    has_edit_text: bool
    reasons: list[str]


def now_timestamp() -> str:
    """Returns a filesystem-safe timestamp for run folders."""
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def slugify_windows_safe(name: str) -> str:
    """
    Normalizes a string into a Windows-safe folder name.

    - Removes invalid characters
    - Collapses whitespace
    - Ensures non-empty fallback
    """
    value = name.strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = value.rstrip(". ")
    if not value:
        value = "unnamed-form"
    return value


def build_output_paths(output_root: Path) -> tuple[Path, Path, Path]:
    """
    Creates the run directory, zip directory, and manifest path.
    """
    run_root = output_root / now_timestamp()
    zip_root = run_root / "zips"
    manifest_path = run_root / "manifest.json"
    return run_root, zip_root, manifest_path


def ensure_directory(path: Path) -> None:
    """Ensures a directory exists."""
    path.mkdir(parents=True, exist_ok=True)


def save_manifest(manifest_path: Path, manifest: dict[str, Any]) -> None:
    """Writes run metadata and results to JSON manifest."""
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def create_browser_context(
    playwright: Playwright,
    state_file: Path,
    headless: bool,
) -> tuple[Browser, BrowserContext]:
    """
    Launches browser and loads persisted session state.

    Enables downloads and reuses authentication from state file.
    """
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context(
        storage_state=str(state_file),
        accept_downloads=True,
    )
    return browser, context


def wait_for_page_to_settle(page: Page, wait_ms: int = PAGE_SETTLE_WAIT_MS) -> None:
    """
    Simple delay to allow async UI updates to complete.
    """
    page.wait_for_timeout(wait_ms)


def page_probe(page: Page) -> ProbeResult:
    """
    Checks whether the page is authenticated and has expected UI elements.
    """
    final_url = page.url
    final_url_lower = final_url.lower()
    reasons: list[str] = []

    # Detect redirect to login or auth flow
    is_login_redirect = "login" in final_url_lower or "oauth" in final_url_lower
    if is_login_redirect:
        reasons.append("redirected to login flow")

    has_files_text = False
    has_edit_text = False

    # Presence of key UI elements
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

    is_authenticated = (not is_login_redirect) and (has_files_text or has_edit_text)

    return ProbeResult(
        is_authenticated=is_authenticated,
        final_url=final_url,
        has_files_text=has_files_text,
        has_edit_text=has_edit_text,
        reasons=reasons,
    )


def wait_for_files_actions_ready(page: Page) -> None:
    """
    Waits for the file actions toolbar to be visible.

    Ensures the page is ready for interaction.
    """
    page.locator(".file-actions .actions").first.wait_for(state="visible", timeout=10000)


def open_form_files_page(page: Page, form_id: int) -> ProbeResult:
    """
    Navigates to a form's files page and returns probe results.
    """
    url = FORM_FILES_URL_TEMPLATE.format(form_id=form_id)
    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
    page.wait_for_timeout(POST_NAV_WAIT_MS)
    wait_for_files_actions_ready(page)
    wait_for_page_to_settle(page)
    return page_probe(page)


def fail_fast_auth_check(page: Page, form_id: int) -> None:
    """
    Validates session before full scan.

    Stops early if authentication is invalid.
    """
    result = open_form_files_page(page, form_id)

    print(f"Fail-fast auth check for form {form_id}")
    print(f"Final URL: {result.final_url}")
    for reason in result.reasons:
        print(f"  - {reason}")

    if not result.is_authenticated:
        raise RuntimeError(
            "Auth check failed. Session expired or invalid. "
            "Run save-session.py to refresh state."
        )


def is_visible(locator) -> bool:
    """Safe visibility check for Playwright locators."""
    try:
        return locator.is_visible()
    except Exception:
        return False


def prepare_files_for_download(page: Page) -> None:
    """
    Ensures all files are selected before download.

    Handles three UI states:
    - Not in edit mode
    - Edit mode with Select All available
    - Already selected (Deselect All visible)
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
        # Already selected
        page.wait_for_timeout(300)
        return

    raise RuntimeError(
        "Could not determine file selection state."
    )


def click_download_icon_and_wait(page: Page) -> Download:
    """
    Clicks the download button and waits for Playwright download event.
    """
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
    """
    Saves the zip under the top-level zip folder and extracts contents into the form folder.

    Returns:
        (zip_path, extracted_dir)
    """
    ensure_directory(zip_root)
    ensure_directory(form_output_dir)

    zip_name = f"{form_output_dir.name}.zip"
    zip_path = zip_root / zip_name
    extracted_dir = form_output_dir / "extracted"

    download.save_as(str(zip_path))

    # Clean existing extraction if rerun
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
    """
    Builds a unique folder name for a form using ID + filename.
    """
    stem = Path(suggested_filename).stem
    safe_name = slugify_windows_safe(stem)

    prefix = f"{form_id:04d}"

    return run_root / f"{prefix}_{safe_name}"


def shorten_error_message(error_text: str) -> str:
    """
    Trims verbose Playwright errors for cleaner logs.
    """
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
    """
    Reads form IDs from CSV with a 'form_id' column.
    """
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


def resolve_form_ids(max_id: int, failed_form_ids_csv: str) -> list[int]:
    """
    Determines which form IDs to process.

    - Uses CSV if provided
    - Otherwise generates sequential range
    """
    if failed_form_ids_csv:
        return parse_form_ids_csv(Path(failed_form_ids_csv).resolve())

    return list(range(1, max_id + 1))


def scan_and_backup_forms(
    page: Page,
    run_root: Path,
    zip_root: Path,
    form_ids: list[int],
    manifest: dict[str, Any],
) -> None:
    """
    Core loop:
    - Navigate to each form
    - Download files
    - Extract contents
    - Record compact manifest entries
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

            # Detect session expiry mid-run
            if "login" in probe.final_url.lower() or "oauth" in probe.final_url.lower():
                raise RuntimeError("Session expired during scan")

            # Skip forms without accessible files UI
            if not (probe.has_files_text and probe.has_edit_text):
                entry["status"] = "empty"
                results.append(entry)
                print("  - skipped: no accessible files UI")
                continue

            prepare_files_for_download(page)
            download = click_download_icon_and_wait(page)

            suggested_filename = download.suggested_filename
            form_dir = form_output_dir_from_download_name(
                run_root,
                suggested_filename,
                form_id,
            )

            zip_path, extracted_dir = save_and_extract_download(download, zip_root, form_dir)

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
    - Validates inputs
    - Initializes browser/session
    - Runs scan
    - Writes manifest
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    parser.add_argument("--max-id", type=int, default=DEFAULT_MAX_ID)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--failed-form-ids-csv", default=FAILED_FORM_IDS_CSV_DEFAULT)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    state_file = Path(args.state_file).resolve()
    if not state_file.exists():
        print(f"ERROR: Storage state file not found: {state_file}")
        sys.exit(99)

    form_ids = resolve_form_ids(
        max_id=args.max_id,
        failed_form_ids_csv=args.failed_form_ids_csv,
    )

    output_root = Path(args.output_root).resolve()
    run_root, zip_root, manifest_path = build_output_paths(output_root)
    ensure_directory(run_root)
    ensure_directory(zip_root)

    manifest: dict[str, Any] = {
        "started_at": datetime.now().isoformat(),
        "state_file": str(state_file),
        "max_id": args.max_id,
        "failed_form_ids_csv": str(Path(args.failed_form_ids_csv).resolve()) if args.failed_form_ids_csv else None,
        "form_ids": form_ids,
        "headless": args.headless,
        "run_root": str(run_root),
        "zip_root": str(zip_root),
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

            # Validate session before processing all forms
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
        # Persist partial results on failure
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
