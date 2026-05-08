import csv
import json
from pathlib import Path

INPUT_JSON = Path("./form-details/output/form-details-deduped-with-pdf-2026-05-08.json")
OUTPUT_CSV = Path("./form-details/output/form-details.csv")


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        raise ValueError("No rows found in JSON")

    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(rows[0].keys())

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)

        writer.writeheader()
        writer.writerows(rows)


def main():
    rows = load_json(INPUT_JSON)

    if not isinstance(rows, list):
        raise ValueError("JSON root must be a list")

    write_csv(OUTPUT_CSV, rows)

    print(f"Rows written: {len(rows)}")
    print(f"CSV created: {OUTPUT_CSV.resolve()}")


if __name__ == "__main__":
    main()