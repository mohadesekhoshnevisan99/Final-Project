import json
import logging
import time
from uuid import UUID, uuid4

import pika
import psycopg

from .common import connect_db, settings

QUEUE = "paper-similarity-jobs"
logger = logging.getLogger(__name__)


def connect_broker():
    parameters = pika.URLParameters(settings.broker_url)
    parameters.heartbeat = 60
    parameters.socket_timeout = 5
    parameters.blocked_connection_timeout = 10
    return pika.BlockingConnection(parameters)


def create_job(kind: str, object_key: str, cache_key: str | None = None, job_id: UUID | None = None) -> UUID:
    job_id = job_id or uuid4()
    with connect_db() as db:
        db.execute(
            """
            INSERT INTO jobs (id, kind, object_key, cache_key) VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (job_id, kind, object_key, cache_key),
        )
    return job_id


def dispatch_one(channel) -> bool:
    with connect_db() as db:
        job = db.execute(
            """
            SELECT id FROM jobs WHERE published_at IS NULL
            ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
            """
        ).fetchone()
        if job is None:
            return False
        job_id = job["id"]
        channel.basic_publish(
            exchange="",
            routing_key=QUEUE,
            body=json.dumps({"job_id": str(job_id)}).encode("utf-8"),
            properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
            mandatory=True,
        )
        db.execute("UPDATE jobs SET published_at = now() WHERE id = %s", (job_id,))
    logger.info("event=queued job_id=%s", job_id)
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    while True:
        connection = None
        try:
            connection = connect_broker()
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE, durable=True)
            channel.confirm_delivery()
            while True:
                published = dispatch_one(channel)
                connection.process_data_events(time_limit=0 if published else 0.2)
        except (pika.exceptions.AMQPError, psycopg.Error, OSError) as exc:
            logger.warning("event=dispatcher_reconnect detail=%s", exc)
        finally:
            if connection is not None and connection.is_open:
                try:
                    connection.close()
                except pika.exceptions.AMQPError:
                    pass
        time.sleep(2)


if __name__ == "__main__":
    main()
