"""Limite de uso por chave (uid) em memória.

Vale por processo: com N workers do gunicorn, o teto efetivo chega a N vezes o
limite. Para um MVP basta para segurar abuso e custo (Gemini, catálogos); o
nginx ainda limita por IP antes de chegar aqui.
"""
import time
from threading import Lock


class RateLimited(Exception):
    def __init__(self, message, retry_after):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))


class RateLimiter:
    def __init__(self, limit, window_seconds, message, max_keys=4096):
        self.limit = limit
        self.window = window_seconds
        self.message = message
        self.max_keys = max_keys
        self._hits = {}
        self._lock = Lock()

    def hit(self, key, now=None):
        """Conta um uso; levanta RateLimited quando a janela já está cheia."""
        now = time.monotonic() if now is None else now
        with self._lock:
            recent = [moment for moment in self._hits.get(key, ()) if now - moment < self.window]
            if len(recent) >= self.limit:
                self._hits[key] = recent
                raise RateLimited(self.message, self.window - (now - recent[0]))
            recent.append(now)
            self._hits.pop(key, None)
            self._hits[key] = recent
            if len(self._hits) > self.max_keys:
                self._hits.pop(next(iter(self._hits)))