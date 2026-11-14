import re
from pathlib import PureWindowsPath
from typing import Any

from app.content.extract import GENERIC_WORDS


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
        "decoy": "untitled.txt",
        "examples": [
            ("Krinal_Resume.pdf", "resumes", 9, "resume in name"),
            ("Invoice_March.pdf", "finance", 9, "invoice"),
            ("21CS42 Module 3 notes.pdf", "study", 9, "course notes"),
            ("DOC-20221021-WA0004.pdf | text: Income Tax Department Form 16 Certificate", "finance", 9, "tax form per text"),
            ("83a91f2e.pdf", "docs", 5, "unclear name"),
        ],
    },
    "images": {
        "folders": [
            ("graphics", "Images/Graphics", "logos, icons, stickers, emojis, memes, wallpapers, designs, random or numeric names"),
            ("photos", "Images/Photos", "camera photos: IMG_, DSC_, PXL_, WhatsApp Image, dates"),
            ("screenshots", "Images/Screenshots", "names containing Screenshot or Screen Shot"),
        ],
        "decoy": "untitled.png",
        "examples": [
            ("IMG_2041.jpg", "photos", 9, "camera photo"),
            ("Screenshot 2024-01-02.png", "screenshots", 9, "screenshot"),
            ("pepe-happy.png", "graphics", 8, "meme sticker"),
            ("3524403.webp", "graphics", 5, "numeric web image"),
        ],
    },
}

# Small models pull whichever item comes first toward the first folder in
# the list. Item 1 is therefore a throwaway decoy whose right answer *is*
# the first (catch-all) folder; real items start at FIRST_ID and the
# decoy's answer is ignored.
FIRST_ID = 2

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
- Some items include "text:", the start of the file itself. When present, it shows what the file really is; trust it over the name.
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


def build_system_prompt(
    group: str,
    folders: list[tuple[str, str, str]],
    user_examples: list[tuple[str, str]] = (),
) -> str:
    # Shown as name -> label rather than numbered reply lines, so the
    # model can't copy an example's answer onto the item with the same id.
    # The user's own past choices go first, in the same list: a small model
    # follows these examples far more reliably than notes in the message.
    lines = [
        f"{name} -> {label} (this user's own choice; follow it for similar names)"
        for name, label in user_examples
    ] + [
        f"{name} -> {label} ({reason})"
        for name, label, _, reason in GROUPS[group]["examples"]
    ]
    return SYSTEM_PROMPT.format(
        group=group,
        folders="\n".join(f"{label}: {hint}" for label, _, hint in folders),
        examples="\n".join(lines),
    )


def build_batch_prompt(batch: list[dict[str, Any]], decoy: str) -> str:
    lines = [f"1 | {decoy}"]

    for number, file in enumerate(batch, start=FIRST_ID):
        line = f"{number} | {file['name']}"
        parent = parent_folder(file["relative_path"])
        if parent:
            line += f" | in {parent}"
        if file.get("snippet"):
            line += f" | text: {file['snippet']}"
        lines.append(line)

    return "Items:\n" + "\n".join(lines)


# --- Learning from the user's corrections -----------------------------------

# Past corrections shown to the model per group; each costs a few tokens.
MAX_EXAMPLES = 4
MAX_LEARNED_FOLDERS = 10


def _name_words(name: str) -> set[str]:
    words = re.findall(r"[a-z]{3,}", PureWindowsPath(name).stem.lower())
    return set(words) - GENERIC_WORDS


def _belongs_to(correction: dict[str, Any], group: str) -> bool:
    return CATEGORY_GROUP.get(correction.get("category")) == group


def learned_folders(
    corrections: list[dict[str, Any]],
    group: str,
    folders: list[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """Folders the user moved files into that aren't offered yet."""
    taken_labels = {label for label, _, _ in folders} | {"review"}
    taken_paths = {path.lower() for _, path, _ in folders}
    learned = []

    for correction in reversed(corrections):  # Newest first.
        path = correction.get("chosen_destination")
        if (
            correction.get("chosen_action") != "move"
            or not path
            or not _belongs_to(correction, group)
            or path.lower() in taken_paths
        ):
            continue
        label = re.sub(r"[^a-z0-9]+", "-", path.split("/")[-1].lower()).strip("-")
        if not label or label in taken_labels:
            continue
        taken_labels.add(label)
        taken_paths.add(path.lower())
        learned.append((label, path, "a folder this user chose before"))

    return learned[:MAX_LEARNED_FOLDERS]


def relevant_examples(
    files: list[dict[str, Any]],
    corrections: list[dict[str, Any]],
    group: str,
    folders: list[tuple[str, str, str]],
) -> list[tuple[str, str]]:
    """The past corrections whose names share the most words with these files."""
    label_for = {path.lower(): label for label, path, _ in folders}
    file_words = set().union(*(_name_words(file["name"]) for file in files))

    scored = []
    for position, correction in enumerate(corrections):
        label = label_for.get((correction.get("chosen_destination") or "").lower())
        if correction.get("chosen_action") != "move" or not label:
            continue
        if not _belongs_to(correction, group) or "|" in correction["name"]:
            continue
        overlap = len(_name_words(correction["name"]) & file_words)
        if overlap:
            # More shared words first, then the most recent.
            scored.append((overlap, position, correction["name"], label))

    scored.sort(reverse=True)
    return [(name, label) for _, _, name, label in scored[:MAX_EXAMPLES]]
