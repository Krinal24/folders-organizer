# TidyByte

An AI-assisted organizer for messy folders like Downloads. TidyByte scans a
folder, suggests what to delete and where to move everything else, lets you
adjust every suggestion, and only then applies the changes, with undo.

## How it works

1. **Scan**: pick a folder with **Browse…** or paste its path. Lists files
   and sizes. Code projects (folders with `.git`, `package.json`, notebooks,
   …) and datasets (many files of one or two types) are kept together as one
   item; `node_modules`, links and system files are skipped. By default only
   the loose files directly in the folder are organized; folders you made
   are left alone unless you tick "Also organize files inside subfolders".
2. **Rules**: no AI. Finds duplicates (by content hash), the same photo
   saved differently (resized or re-compressed, by perceptual hash, shown
   side by side), leftover downloads, empty files and folders, and old
   installers, and files videos, music, archives and installers by type.
   Suggestions use folders you already have: if a `RESUMES` or `Movies`
   folder exists, files go there instead of a new `Documents/Resumes` or
   `Videos`.
3. **AI**: documents and images are sorted into folders such as
   `Documents/Study` or `Images/Screenshots` by an LLM, in batches, with
   results streamed to the UI as they arrive. For documents with unclear names
   (`DOC-2022…pdf`, `83a91f2e.pdf`) the AI also gets the first ~200
   characters of their text (PDF, DOCX, PPTX, XLSX, TXT), read locally.
   When the AI isn't sure about a file from its name alone, it gets a second
   look with the file's text. Scanned PDFs, which are only pictures of pages,
   are read with the OCR built into Windows, on your machine.
4. **Review**: change any suggestion: move elsewhere, keep, or delete.
5. **Apply**: every change is re-checked against the disk first. Nothing is
   overwritten and deletes go to the Recycle Bin. Everything can be undone
   from the **History** tab, the whole run or just the files you pick: moved
   files go back, and deleted ones are restored from the Recycle Bin (Windows,
   and the freedesktop Trash on Linux) as long as it hasn't been emptied.

The AI only ever suggests. Moving and deleting is done by plain code that
validates each operation itself.

The local API only obeys the TidyByte page: each time the backend starts
it makes a random session key, hands it only to the page (checked by the
browser's Origin header, on `localhost` only), and refuses any request
without it. Other web pages you visit can't use it to touch your files.

### Learning from your changes

- **Rules** you confirm: after changing a suggestion, "Remember for similar
  files" saves a rule such as *names containing `21MAT` go to
  `Documents/Study`*. Rules run before the AI (only exact duplicates come
  first) and are managed in the **Rules** tab.
- **Corrections**: every change you apply is remembered. The AI is shown the
  most similar past choices as examples, and folders you created become
  options it can pick.

## Requirements

- Python 3.12+ (developed on 3.14)
- Node.js 22+
- [Ollama](https://ollama.com) with a model pulled, e.g. `ollama pull gemma3:4b`
  (or a Hugging Face token, see below)

## Setup

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env        # macOS/Linux: cp .env.example .env

# Frontend
cd ../frontend
npm install
```

## Run

```bash
# Terminal 1
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2
cd frontend
npm run dev
```

Open http://localhost:5173, paste a folder path, and scan.

## Configuration (`backend/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `AI_PROVIDER` | `ollama` | `ollama` or `huggingface` |
| `OLLAMA_MODEL` | `gemma3:4b` | Local model to use |
| `AI_BATCH_SIZE` | `40` | Files per AI request |
| `AI_READ_CONTENTS` | `unclear` | Read document text for the AI: `unclear` names and files the AI is unsure about, `all`, or `off` (also turns off OCR) |
| `HF_API_TOKEN` | | Needed for `huggingface` |
| `HF_MODEL` | `Qwen/Qwen3-4B-Instruct-2507` | Hugging Face model |
| `TIDYBYTE_DATA_DIR` | `%LOCALAPPDATA%\TidyByte` | Where rules, corrections and undo journals are kept |
| `JOURNAL_DIR` | `<data dir>\journals` | Override for undo journals only |

## Tests

```bash
cd backend && python -m pytest
cd frontend && npm run lint && npm run build
```

CI runs both on every pull request.
