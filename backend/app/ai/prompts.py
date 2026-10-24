from pathlib import PureWindowsPath
from typing import Any


# Each group gets its own short prompt and folder list; a small model does
# far better choosing among a few folders than among all of them.
# Folders are (label the model answers with, destination path, hint).
# The catch-all comes first: when unsure, small models lean to the first option.
GROUPS = {
    "documents": {
        "folders": [
            ("docs", "Documents/Other", "everything else, including random or numeric names"),
            ("resumes", "Documents/Resumes", "name contains resume, CV or cover letter"),
            ("study", "Documents/Study", "notes, lectures, assignments, answer keys, question papers, textbooks, syllabus, course codes like 21MAT21"),
            ("work", "Documents/Work", "reports, project reports, internship documents, presentations, offer letters, contracts"),
            ("finance", "Documents/Finance", "invoices, receipts, bills, fee payments, bank statements, tax"),
            ("personal", "Documents/Personal", "IDs, certificates, tickets, application forms, acknowledgement slips"),
        ],
        "examples": [
            ("Krinal_Resume.pdf", "resumes", 9, "resume in name"),
            ("Invoice_March.pdf", "finance", 9, "invoice"),
            ("21CS42 Module 3 notes.pdf", "study", 9, "course notes"),
            ("83a91f2e.pdf", "docs", 5, "unclear name"),
        ],
    },
    "images": {
        "folders": [
            ("graphics", "Images/Graphics", "logos, icons, stickers, emojis, memes, wallpapers, designs, random or numeric names"),
            ("photos", "Images/Photos", "camera photos: IMG_, DSC_, PXL_, WhatsApp Image, dates"),
            ("screenshots", "Images/Screenshots", "names containing Screenshot or Screen Shot"),
        ],
        "examples": [
            ("IMG_2041.jpg", "photos", 9, "camera photo"),
            ("Screenshot 2024-01-02.png", "screenshots", 9, "screenshot"),
            ("pepe-happy.png", "graphics", 8, "meme sticker"),
            ("3524403.webp", "graphics", 5, "numeric web image"),
        ],
    },
}

# Files of unknown type are judged against the document folders.
CATEGORY_GROUP = {"documents": "documents", "images": "images", "unknown": "documents"}

# Existing subfolders are offered as destinations too, up to this many.
MAX_EXISTING_FOLDERS = 15


SYSTEM_PROMPT = """You sort {group} into folders. For every item, pick one folder label.

Folders (label: what belongs there):
{folders}
review: only if the item cannot be placed at all

Rules:
- Read the name carefully; it is your main clue.
- Answer only with a label from the list above.
- If an existing folder clearly fits, choose it.
- review is rare: almost every item belongs in a folder.

Examples of good choices:
{examples}

Reply with exactly one line per item and nothing else, in this format:
id|label|confidence 1-9|reason in at most 5 words
Judge every item by its own name only."""


def parent_folder(relative_path: str) -> str:
    parent = PureWindowsPath(relative_path).parent.as_posix()
    return "" if parent == "." else parent


def existing_folders(files: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Top-level folders that already exist, offered as destinations."""
    taken = {"review"}
    for group in GROUPS.values():
        for label, path, _ in group["folders"]:
            taken |= {label, path.lower(), path.split("/")[0].lower()}

    existing = []
    for file in files:
        parent = parent_folder(file["relative_path"])
        if not parent:
            continue
        top = parent.split("/")[0]
        # A "|" would break the reply format.
        if "|" in top or top.lower() in taken:
            continue
        taken.add(top.lower())
        existing.append((top.lower(), top, "existing folder"))

    return existing[:MAX_EXISTING_FOLDERS]


def build_system_prompt(group: str, folders: list[tuple[str, str, str]]) -> str:
    # Shown as name -> label rather than numbered reply lines, so the
    # model can't copy an example's answer onto the item with the same id.
    return SYSTEM_PROMPT.format(
        group=group,
        folders="\n".join(f"{label}: {hint}" for label, _, hint in folders),
        examples="\n".join(
            f"{name} -> {label} ({reason})"
            for name, label, _, reason in GROUPS[group]["examples"]
        ),
    )


def build_batch_prompt(batch: list[dict[str, Any]]) -> str:
    lines = []

    for number, file in enumerate(batch, start=1):
        line = f"{number} | {file['name']}"
        parent = parent_folder(file["relative_path"])
        if parent:
            line += f" | in {parent}"
        lines.append(line)

    return "Items:\n" + "\n".join(lines)
