import os
from pathlib import Path

def delete_exact_filename(root_folder: str, target_filename: str, dry_run: bool = True):
    """
    Find and optionally delete files with an exact filename match
    from the given folder and all subfolders.

    Args:
        root_folder: The top-level folder to search.
        target_filename: The exact file name to match.
        dry_run: If True, only report matches. If False, delete them.
    """
    root_path = Path(root_folder)

    if not root_path.exists():
        print(f"Folder does not exist: {root_path}")
        return

    if not root_path.is_dir():
        print(f"Path is not a folder: {root_path}")
        return

    matches = []

    for current_root, _, files in os.walk(root_path):
        for file_name in files:
            if file_name == target_filename:
                full_path = Path(current_root) / file_name
                matches.append(full_path)

    if not matches:
        print(f'No files found with exact name: "{target_filename}"')
        return

    print(f'\nFound {len(matches)} matching file(s):\n')
    for match in matches:
        print(match)

    if dry_run:
        print("\nDry run enabled. No files were deleted.")
        return

    deleted_count = 0
    failed_count = 0

    print("\nDeleting files...\n")
    for match in matches:
        try:
            match.unlink()
            print(f"Deleted: {match}")
            deleted_count += 1
        except Exception as exc:
            print(f"Failed to delete: {match}")
            print(f"Reason: {exc}")
            failed_count += 1

    print("\nDone.")
    print(f"Deleted: {deleted_count}")
    print(f"Failed: {failed_count}")


if __name__ == "__main__":
    folder_input = input("Enter the folder path to search: ").strip()
    filename_input = input("Enter the exact file name to delete: ").strip()
    dry_run_input = input("Dry run only? (y/n): ").strip().lower()

    dry_run = dry_run_input in {"y", "yes"}

    delete_exact_filename(
        root_folder=folder_input,
        target_filename=filename_input,
        dry_run=dry_run
    )