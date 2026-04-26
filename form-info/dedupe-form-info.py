import json
from pathlib import Path


# File paths
INPUT_FILE = Path("./form-info/output/form-details.json")
OUTPUT_FILE = Path("./form-info/output/form-details-deduped.json")

def load_json_file(file_path):
    with file_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json_file(file_path, data):
    with file_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def remove_consecutive_duplicate_forms(forms):
    """
    Remove consecutive duplicate form names.

    Keeps the first/lower form_id.
    Removes the later/higher form_id.
    """

    # Sort from lowest form_id to highest form_id.
    sorted_forms = sorted(forms, key=lambda form: form["form_id"])

    cleaned_forms = []
    previous_form_name = None

    for form in sorted_forms:
        current_form_name = form.get("form_name")

        # If the previous form has the same exact name,
        # this is the duplicate with the higher form_id.
        if current_form_name == previous_form_name:
            continue

        cleaned_forms.append(form)
        previous_form_name = current_form_name

    return cleaned_forms


def main():
    forms = load_json_file(INPUT_FILE)
    cleaned_forms = remove_consecutive_duplicate_forms(forms)
    write_json_file(OUTPUT_FILE, cleaned_forms)

    print(f"Original count: {len(forms)}")
    print(f"Cleaned count: {len(cleaned_forms)}")
    print(f"Removed count: {len(forms) - len(cleaned_forms)}")
    print(f"Output written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()