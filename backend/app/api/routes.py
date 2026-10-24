
from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    ScanRequest,
    ScanResult,
    HealthResponse,
)
from app.models.ai_schemas import AnalyzeRequest, CleanupPlan
from app.scanner.scanner import scan_folder
from app.ai.ollama_analyzer import OllamaAnalyzer


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


@router.post("/analyze", response_model=CleanupPlan)
def analyze(request: AnalyzeRequest):
    try:
        analyzer = OllamaAnalyzer()

        plan = analyzer.analyze(request.files)

        return plan

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=f"AI returned an invalid cleanup plan: {error}",
        )

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"AI analysis failed: {error}",
        )
