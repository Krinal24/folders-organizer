import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models.schemas import (
    ScanRequest,
    ScanResult,
    HealthResponse,
)
from app.models.plan_schemas import AnalyzeRequest
from app.planner import stream_plan
from app.scanner.scanner import scan_folder


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check():
    return {"status": "ok"}


@router.post("/scan", response_model=ScanResult)
def scan(request: ScanRequest):
    try:
        return scan_folder(request.path)

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
        events = stream_plan(request.path, use_ai=request.use_ai)

    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    return StreamingResponse(
        (json.dumps(event) + "\n" for event in events),
        media_type="application/x-ndjson",
    )
