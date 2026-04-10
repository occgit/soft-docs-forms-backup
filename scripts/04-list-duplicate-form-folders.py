import csv
import json
import re
from pathlib import Path
from typing import Any


# Root backup directory
BACKUPS_ROOT = Path("backups")

# Backup run folder to inspect
RUN_FOLDER = "2026-04-10_130203"  # update this for the backup run you want to inspect

# Input/output file names within the run folder
MANIFEST_NAME = "manifest.json"
CSV_NAME = "duplicate_form_folders.csv"


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    """
    Loads and validates the manifest JSON.
    """
    with manifest_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Manifest root must be a JSON object: {manifest_path.resolve()}")

    return data


def strip_prepended_form_id(form_folder: str) -> str:
    """
    Removes the numeric prefix added to form folder names.

    Example:
      0042_Program_Degree Proposal Form
    becomes:
      Program_Degree Proposal Form
    """
    return re.sub(r"^\d+_", "", form_folder).strip()


def get_duplicate_form_folder_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Finds duplicate successful form folders by comparing names
    after removing the prepended form ID.

    Keeps the first occurrence and records later duplicates.
    """
    results = manifest.get("results", [])
    if not isinstance(results, list):
        raise ValueError("Manifest field 'results' must be a list.")

    # Tracks the first form_id seen for each base folder name
    first_seen_by_base_name: dict[str, int] = {}
    duplicates: list[dict[str, Any]] = []

    for entry in results:
        if not isinstance(entry, dict):
            continue

        # Only successful downloads are considered
        if entry.get("status") != "success":
            continue

        form_id = entry.get("form_id")
        form_folder = entry.get("form_folder")

        if not isinstance(form_id, int):
            continue
        if not isinstance(form_folder, str) or not form_folder.strip():
            continue

        base_name = strip_prepended_form_id(form_folder)

        # First time seeing this base name, keep it
        if base_name not in first_seen_by_base_name:
            first_seen_by_base_name[base_name] = form_id
            continue

        # Later matches are treated as duplicates
        duplicates.append(
            {
                "form_id": form_id,
                "error": base_name,
            }
        )

    return duplicates


def write_duplicates_csv(csv_path: Path, duplicate_entries: list[dict[str, Any]]) -> None:
    """
    Writes duplicate form folder entries to CSV.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["form_id", "error"])
        for entry in duplicate_entries:
            writer.writerow([entry["form_id"], entry["error"]])


def main() -> None:
    """
    Builds paths, loads the manifest, finds duplicates,
    writes the CSV, and prints a summary.
    """
    run_path = BACKUPS_ROOT / RUN_FOLDER
    manifest_path = run_path / MANIFEST_NAME
    csv_path = run_path / CSV_NAME

    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path.resolve()}")

    manifest = load_manifest(manifest_path)
    duplicate_entries = get_duplicate_form_folder_entries(manifest)
    duplicate_form_ids = [entry["form_id"] for entry in duplicate_entries]

    write_duplicates_csv(csv_path, duplicate_entries)

    print(f"Manifest: {manifest_path.resolve()}")
    print(f"Duplicate form folder count: {len(duplicate_entries)}")
    print(f"CSV written to: {csv_path.resolve()}")
    print("Duplicate form_ids:")
    print(duplicate_form_ids)


if __name__ == "__main__":
    main()
