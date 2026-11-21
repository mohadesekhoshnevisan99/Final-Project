"""Consume search and indexing jobs with acknowledgement after durable completion."""

from concurrent.futures import ThreadPoolExecutor
from functools import partial
import json
import logging
import socket
import time
from uuid import UUID

import pika
from psycopg.types.json import Jsonb

from .broker import QUEUE, connect_broker
from .common import cache_get, cache_set, connect_db, object_store, settings
from .ranking import Embedder, search

log = logging.getLogger("similarity.worker")
MAX_ATTEMPTS = 3
WORKER_ID = socket.gethostname()


def perform_job(conn, job, embedder):
    job_id = job["id"]
    if job["kind"] == "query":
        cached = cache_get(job["cache_key"]) if job["cache_key"] else None
        if cached is not None:
            log.info("event=worker_cache_hit job_id=%s worker_id=%s", job_id, WORKER_ID)
            return cached
        text = object_store.get(job["object_key"])
        start = time.perf_counter()
        embedding = embedder.encode([text])[0]
        log.info(
            "event=embedded job_id=%s worker_id=%s ms=%.1f",
            job_id, WORKER_ID, (time.perf_counter() - start) * 1000,
        )
        start = time.perf_counter()
        results = search(conn, embedding)
        log.info(
            "event=searched job_id=%s worker_id=%s ms=%.1f",
            job_id, WORKER_ID, (time.perf_counter() - start) * 1000,
        )
        return results

    if job["kind"] != "index":
        raise ValueError(f"Unsupported job kind: {job['kind']}")
    papers = json.loads(object_store.get(job["object_key"]))
    embeddings = embedder.encode([paper["abstract"] for paper in papers])
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO papers (arxiv_id, title, authors, abstract, categories, embedding)
            VALUES (%s, %s, %s, %s, %s, %s::vector)
            ON CONFLICT (arxiv_id) DO NOTHING
            """,
            [
                (
                    paper["arxiv_id"], paper["title"], paper["authors"],
                    paper["abstract"], paper["categories"],
                    json.dumps(vector, allow_nan=False),
                )
                for paper, vector in zip(papers, embeddings, strict=True)
            ],
        )
    return {"indexed": len(papers)}


def process_job(job_id: UUID, embedder: Embedder) -> bool:
    """Return true for an ACK, false for a requeue."""
    with connect_db() as conn:
        # Session ownership survives transaction commits and ends on disconnect.
        # A duplicate delivery cannot run concurrently with an active attempt.
        lock = conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS acquired",
            (str(job_id),),
        ).fetchone()
        if not lock["acquired"]:
            time.sleep(0.5)
            return False
        job = conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
        if job is None or job["status"] in {"completed", "failed"}:
            return True
        if job["attempts"] >= MAX_ATTEMPTS:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'failed', error = %s, completed_at = now()
                WHERE id = %s
                """,
                ("Worker attempts exhausted before completion", job_id),
            )
            conn.commit()
            log.error("event=job_failed job_id=%s worker_id=%s", job_id, WORKER_ID)
            return True

        attempt = job["attempts"] + 1
        conn.execute(
            """
            UPDATE jobs
            SET status = 'processing', attempts = %s, started_at = now(), error = NULL
            WHERE id = %s
            """,
            (attempt, job_id),
        )
        conn.commit()
        log.info(
            "event=job_claimed job_id=%s worker_id=%s attempt=%d kind=%s",
            job_id, WORKER_ID, attempt, job["kind"],
        )
        try:
            if job["kind"] == "query" and settings.worker_delay_seconds:
                time.sleep(settings.worker_delay_seconds)
            result = perform_job(conn, job, embedder)
            conn.execute(
                """
                UPDATE jobs
                SET status = 'completed', result = %s, completed_at = now()
                WHERE id = %s
                """,
                (Jsonb(result), job_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            terminal = attempt >= MAX_ATTEMPTS
            log.exception(
                "event=job_attempt_failed job_id=%s worker_id=%s attempt=%d terminal=%s",
                job_id, WORKER_ID, attempt, terminal,
            )
            if terminal:
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'failed', error = %s, completed_at = now()
                    WHERE id = %s
                    """,
                    ("Job failed after three attempts. See worker logs.", job_id),
                )
            else:
                conn.execute("UPDATE jobs SET status = 'pending' WHERE id = %s", (job_id,))
            conn.commit()
            if not terminal:
                time.sleep(attempt)
            return terminal

        if job["kind"] == "query" and job["cache_key"]:
            try:
                cache_set(job["cache_key"], result)
            except Exception:
                log.exception("event=cache_write_failed job_id=%s worker_id=%s", job_id, WORKER_ID)
        log.info("event=job_completed job_id=%s worker_id=%s attempt=%d", job_id, WORKER_ID, attempt)
        return True


def consume(embedder: Embedder):
    connection = connect_broker()
    try:
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE, durable=True)
        channel.basic_qos(prefetch_count=1)

        def settle(delivery_tag, acknowledge):
            if acknowledge:
                channel.basic_ack(delivery_tag)
            else:
                channel.basic_nack(delivery_tag, requeue=True)

        def run_delivery(job_id, delivery_tag):
            try:
                acknowledge = process_job(job_id, embedder)
            except Exception:
                log.exception("event=job_requeued job_id=%s worker_id=%s", job_id, WORKER_ID)
                time.sleep(2)
                acknowledge = False
            try:
                connection.add_callback_threadsafe(partial(settle, delivery_tag, acknowledge))
            except pika.exceptions.ConnectionWrongStateError:
                log.info("event=broker_disconnected_before_ack job_id=%s worker_id=%s", job_id, WORKER_ID)

        with ThreadPoolExecutor(max_workers=1) as pool:
            def on_delivery(ch, delivery, _properties, body):
                try:
                    job_id = UUID(json.loads(body)["job_id"])
                except (KeyError, TypeError, ValueError, AttributeError):
                    log.error("event=invalid_job_message worker_id=%s", WORKER_ID)
                    ch.basic_reject(delivery.delivery_tag, requeue=False)
                    return
                pool.submit(run_delivery, job_id, delivery.delivery_tag)

            channel.basic_consume(queue=QUEUE, on_message_callback=on_delivery, auto_ack=False)
            log.info("event=worker_ready worker_id=%s mode=%s", WORKER_ID, settings.model_mode)
            channel.start_consuming()
    finally:
        if connection.is_open:
            connection.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    embedder = Embedder(settings.model_mode, settings.model_threads)
    while True:
        try:
            consume(embedder)
        except (pika.exceptions.AMQPError, OSError):
            log.exception("event=broker_reconnect worker_id=%s", WORKER_ID)
            time.sleep(3)


if __name__ == "__main__":
    main()
