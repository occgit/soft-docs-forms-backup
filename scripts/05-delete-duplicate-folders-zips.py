import csv
import shutil
from pathlib import Path
from typing import Dict, List


# Root backup directory
BACKUPS_ROOT = Path("backups")

# Backup run folder to inspect
RUN_FOLDER = "2026-04-10_130203"  # update this for the backup run you want to inspect

# Input file listing duplicate form_ids
DUPLICATES_CSV_NAME = "duplicate_form_folders.csv"

# Top-level zip folder (created by your download script)
ZIP_FOLDER_NAME = "zips"

# Safety flag: set to False to perform actual deletions
DRY_RUN = False


def load_duplicate_form_ids(csv_path: Path) -> list[int]:
    """
    Reads duplicate form_ids from CSV.

    Expects a 'form_id' column.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"Duplicate CSV not found: {csv_path.resolve()}")

    form_ids: list[int] = []

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)

        if "form_id" not in (reader.fieldnames or []):
            raise ValueError("CSV must contain a 'form_id' column.")

        for row in reader:
            value = (row.get("form_id") or "").strip()
            if not value:
                continue

            try:
                form_ids.append(int(value))
            except ValueError:
                continue

    return form_ids


def build_form_id_prefix(form_id: int) -> str:
    """
    Builds the folder/file prefix used in naming.

    Example: 42 -> '0042_'
    """
    return f"{form_id:04d}_"


def find_matching_folders(run_path: Path, form_ids: list[int]) -> dict[int, list[Path]]:
    """
    Finds all form folders that match the given form_ids.
    """
    matches: dict[int, list[Path]] = {form_id: [] for form_id in form_ids}

    for child in run_path.iterdir():
        if not child.is_dir():
            continue

        for form_id in form_ids:
            if child.name.startswith(build_form_id_prefix(form_id)):
                matches[form_id].append(child)

    return matches


def find_matching_zips(zip_root: Path, form_ids: list[int]) -> dict[int, list[Path]]:
    """
    Finds zip files in the top-level zip folder that match form_ids.
    """
    matches: dict[int, list[Path]] = {form_id: [] for form_id in form_ids}

    if not zip_root.exists():
        return matches

    for file in zip_root.iterdir():
        if not file.is_file() or not file.name.lower().endswith(".zip"):
            continue

        for form_id in form_ids:
            if file.name.startswith(build_form_id_prefix(form_id)):
                matches[form_id].append(file)

    return matches


def delete_paths(matches: dict[int, list[Path]], dry_run: bool, label: str) -> list[dict[str, str]]:
    """
    Deletes or simulates deletion of folders/files.

    label is used for logging (e.g., 'folder' or 'zip')
    """
    actions: list[dict[str, str]] = []

    for form_id, paths in matches.items():
        if not paths:
            actions.append(
                {
                    "form_id": str(form_id),
                    "status": "not_found",
                    label: "",
                }
            )
            continue

        for path in paths:
            if dry_run:
                actions.append(
                    {
                        "form_id": str(form_id),
                        "status": "would_delete",
                        label: str(path.resolve()),
                    }
                )
            else:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()

                actions.append(
                    {
                        "form_id": str(form_id),
                        "status": "deleted",
                        label: str(path.resolve()),
                    }
                )

    return actions


def main() -> None:
    """
    - Loads duplicate form_ids
    - Finds matching folders and zip files
    - Deletes (or simulates deletion)
    - Prints a summary
    """
    run_path = BACKUPS_ROOT / RUN_FOLDER
    duplicates_csv_path = run_path / DUPLICATES_CSV_NAME
    zip_root = run_path / ZIP_FOLDER_NAME

    if not run_path.exists():
        raise FileNotFoundError(f"Run folder not found: {run_path.resolve()}")

    form_ids = load_duplicate_form_ids(duplicates_csv_path)
    if not form_ids:
        print(f"No form_ids found in: {duplicates_csv_path.resolve()}")
        return

    # Find matching folders and zip files
    folder_matches = find_matching_folders(run_path, form_ids)
    zip_matches = find_matching_zips(zip_root, form_ids)

    # Perform deletions
    folder_actions = delete_paths(folder_matches, dry_run=DRY_RUN, label="folder")
    zip_actions = delete_paths(zip_matches, dry_run=DRY_RUN, label="zip")

    print(f"Run folder: {run_path.resolve()}")
    print(f"Duplicate CSV: {duplicates_csv_path.resolve()}")
    print(f"Zip folder: {zip_root.resolve()}")
    print(f"Dry run: {DRY_RUN}")
    print("")

    print("=== FOLDER ACTIONS ===")
    for action in folder_actions:
        print(f"{action['form_id']}: {action['status']} -> {action['folder']}")

    print("\n=== ZIP ACTIONS ===")
    for action in zip_actions:
        print(f"{action['form_id']}: {action['status']} -> {action['zip']}")


if __name__ == "__main__":
    main()
