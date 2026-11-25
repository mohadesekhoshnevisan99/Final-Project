import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psycopg
import redis
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    database_url: str = os.environ.get("APP_DATABASE_URL", "postgresql://papers:papers@db/papers")
    broker_url: str = os.environ.get("APP_BROKER_URL", "amqp://papers:papers@rabbitmq:5672/%2F")
    redis_url: str = os.environ.get("APP_REDIS_URL", "redis://redis:6379/0")
    cache_enabled: bool = os.environ.get("APP_CACHE_ENABLED", "true").lower() == "true"
    storage_dir: Path = Path(os.environ.get("APP_STORAGE_DIR", "/objects"))
    model_mode: str = os.environ.get("APP_MODEL_MODE", "minilm")
    model_threads: int = int(os.environ.get("APP_MODEL_THREADS", "1"))
    worker_delay_seconds: float = float(os.environ.get("APP_WORKER_DELAY_SECONDS", "0"))


settings = Settings()


def connect_db():
    return psycopg.connect(settings.database_url, row_factory=dict_row, connect_timeout=5)


class ObjectStore:
    def local_path(self, key: str) -> Path:
        root = settings.storage_dir.resolve()
        path = (root / key).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError("Invalid object key")
        return path

    def put(self, key: str, value: str) -> None:
        path = self.local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(value.encode("utf-8"))
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, key: str) -> str:
        return self.local_path(key).read_bytes().decode("utf-8")


object_store = ObjectStore()
cache = redis.Redis.from_url(settings.redis_url, socket_timeout=0.5, socket_connect_timeout=0.5)
CACHE_TTL = 3600


def cache_get(key: str) -> list | None:
    if settings.cache_enabled:
        try:
            value = cache.get(key)
            if value is not None:
                return json.loads(value)
        except (redis.RedisError, ValueError) as exc:
            logger.warning("cache read unavailable: %s", type(exc).__name__)
    return None


def cache_set(key: str, results: list) -> None:
    if settings.cache_enabled:
        try:
            cache.set(key, json.dumps(results, ensure_ascii=False), ex=CACHE_TTL)
        except redis.RedisError as exc:
            logger.warning("cache write unavailable: %s", type(exc).__name__)
