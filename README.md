# TidyByte

An AI-assisted organizer for messy folders like Downloads. TidyByte scans a
folder, suggests what to delete and where to move everything else, lets you
adjust every suggestion, and only then applies the changes, with undo.

## How it works

1. **Scan**: lists files and sizes. Code projects (folders with `.git`,
   `package.json`, …) are kept together as one item, and `node_modules`,
   links and system files are skipped.
2. **Rules**: instant, no AI. Finds duplicates (by content hash), leftover
   downloads, empty files and folders, and old installers, and files videos,
   music, archives and installers by type.
3. **AI**: documents and images are sorted into folders such as
   `Documents/Study` or `Images/Screenshots` by an LLM, in batches, with
   results streamed to the UI as they arrive.
4. **Review**: change any suggestion: move elsewhere, keep, or delete.
5. **Apply**: every change is re-checked against the disk first. Nothing is
   overwritten, deletes go to the Recycle Bin, and moves can be undone.

The AI only ever suggests. Moving and deleting is done by plain code that
validates each operation itself.

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
| `HF_API_TOKEN` | | Needed for `huggingface` |
| `HF_MODEL` | `Qwen/Qwen3-4B-Instruct-2507` | Hugging Face model |
| `JOURNAL_DIR` | `%LOCALAPPDATA%\TidyByte\journals` | Where undo journals are kept |

## Tests

```bash
cd backend && python -m pytest
cd frontend && npm run lint && npm run build
```

CI runs both on every pull request.
