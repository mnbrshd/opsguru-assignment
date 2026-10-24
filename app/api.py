"""Thin HTTP API: POST /ask

Run:
  python -m app.api
  # or: uvicorn app.api:app --reload --port 8000
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.pipeline import DEFAULT_CSV, DEFAULT_DB, run_pipeline
from app.query_agent import ask


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    use_llm: bool = True


class AskResponse(BaseModel):
    answer: str
    sql: str
    rows: list[dict]
    rows_cited: int
    warnings: list[str]
    mode: str


def _ensure_db() -> Path:
    csv_path = Path(os.getenv("CLOUDNOVA_CSV", DEFAULT_CSV))
    db_path = Path(os.getenv("CLOUDNOVA_DB", DEFAULT_DB))
    if not db_path.exists():
        run_pipeline(csv_path, db_path)
    return db_path


@asynccontextmanager
async def lifespan(_app: FastAPI):
    load_dotenv()
    _ensure_db()
    yield


app = FastAPI(
    title="CloudNova Ask API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def post_ask(body: AskRequest) -> AskResponse:
    db_path = _ensure_db()
    result = ask(body.question, db_path=db_path, use_llm=body.use_llm)
    if result.mode == "error" and not result.sql:
        raise HTTPException(status_code=422, detail=result.to_dict())
    return AskResponse(**result.to_dict())


def main() -> None:
    import uvicorn

    load_dotenv()
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run("app.api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
