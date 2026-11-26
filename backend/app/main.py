from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.api.routes import open_router, router  # noqa: E402
from app.security import HEADER, allowed_origins  # noqa: E402


app = FastAPI(
    title="TidyByte",
    description="AI-powered folder organizer",
    version="0.1.0"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", HEADER],
)


app.include_router(open_router, prefix="/api")
app.include_router(router, prefix="/api")
