"""Request correlation, timing, and a body-size ceiling.

A production log has to answer "what happened to the request at 14:03" without
a bisect. Every line emitted while handling a request carries the same
request_id, and the id goes back in a response header so a caller reporting a
problem can quote it.
"""
from __future__ import annotations

import contextvars
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    'request_id', default='-')

log = logging.getLogger('audit.http')


class RequestIdFilter(logging.Filter):
    """Stamps every record with the request being served, if any."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = REQUEST_ID.get()
        return True


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Correlation id + access log + latency header."""

    async def dispatch(self, request, call_next):
        rid = (request.headers.get('x-request-id')
               or uuid.uuid4().hex[:12])
        token = REQUEST_ID.set(rid)
        t0 = time.time()
        try:
            response = await call_next(request)
        except Exception:
            # Log with the id BEFORE the handler unwinds, or the trace and the
            # request cannot be tied together afterwards.
            log.exception('%s %s -> unhandled', request.method,
                          request.url.path)
            REQUEST_ID.reset(token)
            raise
        dt = (time.time() - t0) * 1000
        response.headers['x-request-id'] = rid
        response.headers['x-response-time-ms'] = f'{dt:.0f}'
        # /health is polled every few seconds by every platform in existence.
        # Logging it drowns the signal.
        if request.url.path not in ('/health', '/ready', '/metrics'):
            log.info('%s %s -> %s  %.0fms', request.method, request.url.path,
                     response.status_code, dt)
        REQUEST_ID.reset(token)
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Refuse an oversized body early, with a reason.

    Every endpoint here takes a small JSON document -- a handful of URLs, or a
    brief. Without a ceiling, an unauthenticated caller can make the process
    buffer arbitrary bytes, and on a 512 MB free-tier container that is the
    whole attack.
    """

    def __init__(self, app, max_bytes: int = 2 * 1024 * 1024):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request, call_next):
        declared = request.headers.get('content-length')
        if declared and declared.isdigit() and int(declared) > self.max_bytes:
            return JSONResponse(
                status_code=413,
                content={'error': 'PayloadTooLarge',
                         'detail': f'body exceeds {self.max_bytes} bytes. '
                                   f'This API takes URLs and brief text, not '
                                   f'uploads.'})
        return await call_next(request)
