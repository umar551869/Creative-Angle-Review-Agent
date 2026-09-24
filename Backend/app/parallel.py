"""Bounded parallelism that does not lose the job's context.

THE TRAP THIS EXISTS TO AVOID
-----------------------------
`DIRS` is a ContextVar, so the pipeline can write `DIRS['inbox']` and get the
paths belonging to the job running on this task. A ContextVar is per-context,
and **ThreadPoolExecutor does not copy the calling context into its workers**.
So a naive `pool.submit(fn, x)` inside a job silently runs with DIRS unset,
falls back to the SHARED inbox, and two concurrent jobs start reading each
other's videos.

Nothing raises. The files are all real, the paths all exist, and the wrong
video gets audited against the wrong brief. `copy_context()` per task is the
whole fix, and it is the only reason this module exists rather than a bare
ThreadPoolExecutor at each call site.
"""
from __future__ import annotations

import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterable, Sequence, TypeVar

log = logging.getLogger('audit.parallel')

T = TypeVar('T')
R = TypeVar('R')


def run_parallel(items: Sequence[T], fn: Callable[[T], R], *,
                 workers: int, label: str = 'task',
                 on_error: Callable[[T, Exception], R] | None = None,
                 ) -> list[R]:
    """Apply `fn` to every item, at most `workers` at a time, IN ORDER out.

    Results come back in the order of `items`, not completion order, because
    every caller here builds a per-video table and a reordered table is a
    table that quietly stops lining up with its input.

    workers <= 1 runs inline: no threads, no context copying, nothing to
    reason about. That is what makes AUDITOR_*_WORKERS=1 a true restoration
    of sequential behaviour rather than an approximation of it.

    An exception in one item never cancels the rest -- one bad video must not
    cost the other nine. Without `on_error` the exception is re-raised after
    the batch, with the item named.
    """
    items = list(items)
    if not items:
        return []
    workers = max(1, int(workers))
    if workers == 1 or len(items) == 1:
        out = []
        for it in items:
            try:
                out.append(fn(it))
            except Exception as exc:
                if on_error is None:
                    raise
                out.append(on_error(it, exc))
        return out

    log.info('%s: %d item(s) across %d worker(s)', label, len(items), workers)
    results: list[Any] = [None] * len(items)
    errors: list[tuple[int, T, Exception]] = []

    with ThreadPoolExecutor(max_workers=workers,
                            thread_name_prefix=f'audit-{label}') as pool:
        futures = {}
        for i, it in enumerate(items):
            # THE LINE THAT MATTERS. Without it the worker has no DIRS.
            ctx = contextvars.copy_context()
            futures[pool.submit(ctx.run, fn, it)] = (i, it)
        for fut in as_completed(futures):
            i, it = futures[fut]
            try:
                results[i] = fut.result()
            except Exception as exc:
                if on_error is None:
                    errors.append((i, it, exc))
                else:
                    results[i] = on_error(it, exc)

    if errors:
        i, it, exc = errors[0]
        raise RuntimeError(
            f'{label}: {len(errors)} of {len(items)} failed; first was '
            f'item {i} ({it!r:.80}): {type(exc).__name__}: {exc}') from exc
    return results
