import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse

from app.models.schemas import (
    ScanRequest,
    ScanResult,
    HealthResponse,
)
from app.executor.executor import AlreadyUndone, execute_plan, get_run, list_runs, undo
from app.learning import store as learning
from app.models.plan_schemas import (
    AnalyzeRequest,
    ExecuteRequest,
    PickFolderRequest,
    RuleRequest,
    UndoRequest,
)
from app.picker import PickerUnavailable, pick_folder
from app.planner import stream_plan
from app.rules.photos import PHOTO_SUFFIXES, thumbnail
from app.scanner.scanner import scan_folder


router = APIRouter()

# Folders scanned in this session; thumbnails are only served from these.
scanned_roots: set[Path] = set()


@router.get("/health", response_model=HealthResponse)
def health_check():
    return {"status": "ok"}


@router.post("/scan", response_model=ScanResult)
def scan(request: ScanRequest):
    try:
        result = scan_folder(request.path)
        scanned_roots.add(Path(result["path"]).resolve())
        return result

    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/analyze")
def analyze(request: AnalyzeRequest):
    """
    Streams newline-delimited JSON events (see planner.stream_plan):
    rule results arrive at once, AI results one by one after that.
    """
    try:
        events = stream_plan(
            request.path,
            use_ai=request.use_ai,
            read_contents=request.read_contents,
            include_subfolders=request.include_subfolders,
        )
        scanned_roots.add(Path(request.path).expanduser().resolve())

    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    return _ndjson(events)


def _ndjson(events):
    return StreamingResponse(
        (json.dumps(event) + "\n" for event in events),
        media_type="application/x-ndjson",
    )


@router.post("/execute")
def execute(request: ExecuteRequest):
    """
    Applies the moves and deletes the user approved, re-checking each one
    against the disk. Streams one event per operation (see execute_plan).
    """
    try:
        events = execute_plan(
            request.path,
            [operation.model_dump() for operation in request.operations],
        )
        # Only after the folder checked out; applied changes are what we learn from.
        learning.record_corrections(
            [correction.model_dump() for correction in request.corrections]
        )

    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    return _ndjson(events)


@router.get("/runs")
def runs():
    """Past runs, newest first, with what they changed and whether undone."""
    return list_runs()


@router.get("/runs/{run_id}")
def run_details(run_id: str):
    try:
        return get_run(run_id)

    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/undo")
def undo_run(request: UndoRequest):
    try:
        return undo(request.journal_id)

    except AlreadyUndone as error:
        raise HTTPException(status_code=409, detail=str(error))

    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/learned")
def learned():
    """The user's saved rules and the corrections the AI learns from."""
    corrections = learning.list_corrections()
    return {
        "rules": sorted(learning.list_rules(), key=lambda r: r["created"], reverse=True),
        "corrections": len(corrections),
        "recent_corrections": corrections[-10:][::-1],
    }


@router.post("/rules")
def add_rule(request: RuleRequest):
    try:
        return learning.add_rule(request.contains, request.action, request.destination)

    except learning.InvalidRule as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str):
    try:
        learning.delete_rule(rule_id)
        return {"deleted": rule_id}

    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.delete("/corrections")
def forget_corrections():
    learning.clear_corrections()
    return {"corrections": 0}


@router.post("/pick-folder")
def choose_folder(request: PickFolderRequest):
    """Open the system folder dialog; path is null if the user cancels."""
    try:
        return {"path": pick_folder(request.initial)}

    except PickerUnavailable as error:
        raise HTTPException(status_code=501, detail=str(error))


@router.get("/thumbnail")
def photo_thumbnail(root: str, path: str):
    """A small JPEG of a photo inside a folder scanned in this session."""
    root_path = Path(root).expanduser().resolve()
    if root_path not in scanned_roots:
        raise HTTPException(status_code=403, detail="Scan this folder first.")

    photo = (root_path / path).resolve()
    if not photo.is_relative_to(root_path) or photo == root_path:
        raise HTTPException(status_code=403, detail="Outside the scanned folder.")
    if photo.suffix.lower() not in PHOTO_SUFFIXES or not photo.is_file():
        raise HTTPException(status_code=404, detail="No such photo.")

    try:
        image = thumbnail(photo)
    except Exception:
        raise HTTPException(status_code=415, detail="Can't read this image.")
    return Response(image, media_type="image/jpeg", headers={"Cache-Control": "max-age=300"})

