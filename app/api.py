"""Thin HTTP API: POST /ask (+ optional API key auth, multi-turn history)

Run:
  python -m app.api
"""

from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.pipeline import DEFAULT_CSV, DEFAULT_DB, run_pipeline
from app.query_agent import ask

# In-memory multi-turn sessions (process-local; fine for the demo)
_SESSIONS: dict[str, list[dict[str, str]]] = {}


class HistoryTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    use_llm: bool = True
    history: list[HistoryTurn] | None = None
    session_id: str | None = Field(default=None, max_length=64)
    start_session: bool = False


class AskResponse(BaseModel):
    answer: str
    sql: str
    rows: list[dict]
    rows_cited: int
    warnings: list[str]
    mode: str
    session_id: str | None = None


def _ensure_db() -> Path:
    csv_path = Path(os.getenv("CLOUDNOVA_CSV", DEFAULT_CSV))
    db_path = Path(os.getenv("CLOUDNOVA_DB", DEFAULT_DB))
    if not db_path.exists():
        run_pipeline(csv_path, db_path)
    return db_path


def require_api_key(
    x_api_key: Annotated[str | None, Header()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """If CLOUDNOVA_API_KEY is set, require matching X-API-Key or Bearer token."""
    expected = os.getenv("CLOUDNOVA_API_KEY", "").strip()
    if not expected:
        return
    provided = (x_api_key or "").strip()
    if not provided and authorization:
        auth = authorization.strip()
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    load_dotenv()
    _ensure_db()
    yield


app = FastAPI(
    title="CloudNova Ask API",
    version="0.2.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse, dependencies=[Depends(require_api_key)])
def post_ask(body: AskRequest) -> AskResponse:
    db_path = _ensure_db()
    session_id = body.session_id
    if body.start_session and not session_id:
        session_id = secrets.token_hex(8)

    history: list[dict[str, str]] = []
    if session_id:
        history = list(_SESSIONS.get(session_id, []))
    elif body.history:
        history = [t.model_dump() for t in body.history]

    result = ask(
        body.question,
        db_path=db_path,
        use_llm=body.use_llm,
        history=history or None,
    )
    if result.mode == "error" and not result.sql:
        raise HTTPException(status_code=422, detail=result.to_dict())

    if session_id:
        turns = _SESSIONS.setdefault(session_id, [])
        turns.append({"role": "user", "content": body.question})
        turns.append(
            {"role": "assistant", "content": f"{result.answer}\nSQL: {result.sql}"}
        )
        _SESSIONS[session_id] = turns[-12:]

    payload = result.to_dict()
    payload["session_id"] = session_id
    return AskResponse(**payload)


def main() -> None:
    import uvicorn

    load_dotenv()
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run("app.api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
