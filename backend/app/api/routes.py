from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    ScanRequest,
    ScanResult,
    HealthResponse
)
from app.scanner.scanner import scan_downloads


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health_check():
    return {"status": "ok"}


@router.post("/scan", response_model=ScanResult)
def scan(request: ScanRequest):
    try:
        return scan_downloads(request.downloads_path)

    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error)
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error)
        )