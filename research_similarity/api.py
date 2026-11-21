import hashlib
import logging
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.concurrency import run_in_threadpool

from .broker import create_job
from .common import cache_get, connect_db, object_store, settings

logger = logging.getLogger(__name__)
app = FastAPI(title="Research-Paper Similarity Service", version="1.0.0")
web = Path(__file__).with_name("web")
app.mount("/assets", StaticFiles(directory=web), name="assets")


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str


def ready_snapshot():
    with connect_db() as db:
        return db.execute(
            "SELECT paper_count, digest FROM corpus_snapshot WHERE status = 'completed' AND model_mode = %s",
            (settings.model_mode,),
        ).fetchone()


def paper_count() -> int:
    row = ready_snapshot()
    return row["paper_count"] if row else 0


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(web / "index.html")


@app.get("/healthz")
def health():
    try:
        return {"status": "ok", "papers": paper_count(), "model": settings.model_mode}
    except psycopg.Error as exc:
        raise HTTPException(503, "Database unavailable") from exc


def submit_query(text: str):
    try:
        snapshot = ready_snapshot()
        if not snapshot or not snapshot["paper_count"]:
            raise HTTPException(503, "The paper corpus is not ready")
    except psycopg.Error as exc:
        raise HTTPException(503, "Database unavailable") from exc

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    key = f"paper-similarity:v1:{settings.model_mode}:{snapshot['digest']}:{digest}"
    cached = cache_get(key)
    if cached is not None:
        return JSONResponse(
            {"job_id": None, "status": "completed", "results": cached, "cache_hit": True,
             "error": None, "attempts": None}
        )

    object_key = f"queries/{uuid4()}.txt"
    try:
        object_store.put(object_key, text)
        job_id = create_job("query", object_key, key)
    except Exception as exc:
        logger.error("event=submit_failed error_type=%s", type(exc).__name__)
        raise HTTPException(503, "Could not store the query. Please retry.") from exc
    logger.info("event=accepted job_id=%s", job_id)
    return JSONResponse(
        {"job_id": str(job_id), "status": "pending", "results": None, "cache_hit": False,
         "error": None, "attempts": 0},
        status_code=202,
        headers={"Location": f"/jobs/{job_id}"},
    )


@app.post(
    "/jobs", status_code=202, responses={200: {"description": "Cached result"}},
    openapi_extra={"requestBody": {"required": True, "content": {
        "application/json": {"schema": Query.model_json_schema(), "example": {
            "text": "Dense passage retrieval with a dual encoder for open-domain question answering."
        }}
    }}},
)
async def post_job(request: Request):
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 65_536:
            raise HTTPException(413, "Request body exceeds 64 KiB")
        body.extend(chunk)
    try:
        query = Query.model_validate_json(body)
        text = " ".join(query.text.split())
        text.encode("utf-8")
    except (ValidationError, UnicodeError) as exc:
        raise HTTPException(422, 'Expected a JSON object with a plain-text "text" field') from exc
    if not 1 <= len(text) <= 12_000 or "\x00" in text:
        raise HTTPException(422, "Enter between 1 and 12,000 characters of plain text")
    return await run_in_threadpool(submit_query, text)


@app.get("/jobs/{job_id}")
def job_status(job_id: UUID):
    try:
        with connect_db() as db:
            row = db.execute(
                "SELECT status, result, error, attempts FROM jobs WHERE id = %s AND kind = 'query'",
                (job_id,),
            ).fetchone()
    except psycopg.Error as exc:
        raise HTTPException(503, "Database unavailable") from exc
    if row is None:
        raise HTTPException(404, "Job not found")
    return {"job_id": job_id, "status": row["status"], "results": row["result"], "cache_hit": False,
            "error": row["error"], "attempts": row["attempts"]}
