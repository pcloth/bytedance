"""Application credentials, isolated by application, environment and type."""
import contextlib
import hashlib
import json
import os
import tempfile
import threading
import time

from .base import ByteDanceError

try:
    import redis
except ImportError:
    redis = None


@contextlib.contextmanager
def file_lock(path):
    """Cross-process lock on Unix and Windows (also available on Python 3.6)."""
    with open(path, "a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if os.path.getsize(path) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def token_string(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, str) or not value.strip():
        raise ByteDanceError("Credential provider returned an empty or invalid token")
    return value.strip()


class TokenCache(object):
    def __init__(self, client, config):
        self.client = client
        self.mode = client.access_token_type
        self.provider = config.get("token_provider")
        self._thread_lock = threading.RLock()
        self.redis = None
        if self.mode == "redis" and redis is None:
            raise ByteDanceError("Redis mode requires pip install bytedance[redis]")
        if self.mode in ("auto", "redis") and redis is not None:
            options = dict(client.redis_conf)
            options.setdefault("socket_connect_timeout", 2)
            options.setdefault("socket_timeout", 2)
            self.redis = redis.Redis(**options)
        identity = "{}:{}".format(client.app_id, client.environment)
        self.namespace = "bytedance:" + hashlib.sha256(identity.encode()).hexdigest()[:32]

    def get(self, kind):
        if self.provider is not None:
            supplied = self.provider(kind)
            if supplied is not None:
                return token_string(supplied)
        with self._thread_lock:
            if self.redis is not None:
                try:
                    return self._redis_get(kind)
                except redis.exceptions.RedisError as exc:
                    if self.mode == "redis":
                        raise ByteDanceError("Redis credential cache failed: {}".format(exc)) from exc
            return self._file_get(kind)

    def _refresh(self, kind):
        result = self.client._fetch_application_token(kind)
        value = token_string(result.get("access_token"))
        try:
            lifetime = float(result["expires_in"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ByteDanceError("Credential response has invalid expires_in") from exc
        if lifetime <= 0:
            raise ByteDanceError("Credential response has expired")
        ttl = max(1, int(lifetime - min(600, lifetime * 0.1)))
        return {"token": value, "expires_at": time.time() + ttl}, ttl

    def _redis_get(self, kind):
        key = self.namespace + ":" + kind
        value = self.redis.get(key)
        if value:
            return token_string(value)
        with self.redis.lock(key + ":lock", timeout=90, blocking_timeout=30):
            value = self.redis.get(key)
            if value:
                return token_string(value)
            record, ttl = self._refresh(kind)
            self.redis.set(key, record["token"], ex=ttl)
            return record["token"]

    def _path(self, kind):
        path = self.client.ac_path
        suffix = self.namespace.split(":", 1)[1]
        return "{}.{}.{}.json".format(path, suffix, kind)

    def _file_get(self, kind):
        path = os.path.abspath(self._path(kind))
        parent = os.path.dirname(path)
        os.makedirs(parent, exist_ok=True)
        with file_lock(path + ".lock"):
            try:
                read_path = path
                if (not os.path.exists(path) and kind == "mini_app" and
                        self.client.environment == "production" and os.path.exists(self.client.ac_path)):
                    read_path = self.client.ac_path
                with open(read_path, encoding="utf-8") as stream:
                    raw = stream.read()
                try:
                    record = json.loads(raw)
                except ValueError:
                    record = {"token": raw, "expires_at": os.path.getmtime(read_path)}
                if isinstance(record, dict) and float(record.get("expires_at", 0)) > time.time():
                    return token_string(record.get("token"))
            except (OSError, ValueError, TypeError, ByteDanceError):
                pass
            record, _ = self._refresh(kind)
            fd, temporary = tempfile.mkstemp(prefix=".bytedance-", dir=parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(record, stream)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return record["token"]
