import json
from pathlib import Path


# ---- CONFIG ----
INPUT_FILE = Path("./misc/form-info-input.txt")
OUTPUT_FILE = Path("./output/form-info.json")
# ----------------


def parse_txt_to_object(file_path: Path) -> dict:
    """
    Convert the txt file into a JSON object.

    Expected format:
    0: form_id
    1: form_name
    2: department
    3: form_group
    4: anonymous (blank = False, anything = True)
    5: published (blank = False, anything = True)
    """
    lines = [line.strip() for line in file_path.read_text(encoding="utf-8").splitlines()]

    # Ensure we always have at least 6 lines
    while len(lines) < 6:
        lines.append("")

    return {
        "form_id": int(lines[0]) if lines[0] else None,
        "form_name": lines[1],
        "department": lines[2],
        "form_group": lines[3],
        "anonymous": bool(lines[4]),
        "published": not bool(lines[5]),
    }


def append_to_json(output_path: Path, new_object: dict) -> None:
    """
    Append the object to a JSON file.
    Creates the file if it does not exist.
    """
    if output_path.exists():
        try:
            data = json.loads(output_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                data = []
        except json.JSONDecodeError:
            data = []
    else:
        data = []

    data.append(new_object)

    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main():
    if not INPUT_FILE.exists():
        print(f"Input file not found: {INPUT_FILE}")
        return

    obj = parse_txt_to_object(INPUT_FILE)
    append_to_json(OUTPUT_FILE, obj)

    print("Data added to JSON file.")


if __name__ == "__main__":
    main()