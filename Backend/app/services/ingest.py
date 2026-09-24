"""Getting the inputs in: videos by URL, the brief by Google Doc URL or text.

Both reuse the notebook's own loaders rather than reimplementing them, because
both carry hard-won behaviour that is easy to lose in a rewrite:

  * `download_videos` decides success by asking whether a video with the
     resolved id is IN THE INBOX -- not by trusting yt-dlp's intended filename
     (wrong after a merge) and not by diffing the directory (wrong on a
     re-run, when yt-dlp skips a file it already has).
  * `load_brief_text` refuses a Google Doc that came back as an HTML sign-in
     page. That HTML would otherwise compile into real-looking requirements,
     which is far worse than failing outright.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Optional

from app.parallel import run_parallel
from auditor import runtime

log = logging.getLogger('audit.ingest')


class IngestError(RuntimeError):
    def __init__(self, phase: str, message: str):
        super().__init__(message)
        self.phase = phase


# ---------------------------------------------------------------------------
# Videos
# ---------------------------------------------------------------------------
def _video_id(url: str) -> str:
    """The trailing digits of a TikTok URL are the id downloads are named by."""
    m = re.search(r'(\d{6,})(?:\?|$|/)', url or '')
    return m.group(1) if m else ''


def download_videos(urls: list[str], *, cookies_file: str = '',
                    workers: int = 1) -> dict:
    """Fetch every URL into THIS job's inbox. Never raises on a bad link.

    A private, deleted or region-locked link is normal in a list of twenty and
    must cost that one video, not the whole job.

    PARALLEL BY URL, and safe to be: each fetch is independent network wait
    writing a file named by the video id, so there is no shared state to race
    on. The notebook's own per-URL logic is reused -- format ladder, browser
    UA, cookies, retries -- rather than reimplemented.

    What is NOT reused is its return value. `download_videos` decides success
    partly by diffing the inbox, and concurrently that diff sees files other
    workers just landed. Harmless if ignored, wrong if trusted, so each worker
    confirms its OWN id is present instead. Which is the same lesson fix 56
    landed on: ask whether the artifact is there, not whether the call worked.
    """
    ns = runtime.load()
    if cookies_file:
        # The notebook reads COOKIES_FILE as a module global in the same cell.
        ns['COOKIES_FILE'] = cookies_file
    inbox = ns['DIRS']['inbox']
    t0 = time.time()

    def _fetch(url: str) -> tuple[str, Optional[Path]]:
        try:
            ns['download_videos']([url], verbose=False)
        except Exception as exc:                 # it should not raise; belt
            log.warning('download raised for %s: %s', url[:60], exc)
        vid = _video_id(url)
        hit = next((p for p in sorted(inbox.iterdir())
                    if p.is_file() and ns['_is_video'](p.name)
                    and (not vid or p.stem.startswith(vid))), None)
        return url, hit

    pairs = run_parallel(list(urls), _fetch, workers=workers,
                         label='download',
                         on_error=lambda u, e: (u, None))
    failed = [u for u, hit in pairs if hit is None]
    for u in failed:
        log.warning('could not download: %s', u)

    present = sorted(p for p in inbox.iterdir()
                     if p.is_file() and ns['_is_video'](p.name))
    log.info('ingest: %d/%d link(s) in the inbox after %.1fs',
             len(urls) - len(failed), len(urls), time.time() - t0)
    if not present:
        raise IngestError(
            'ingest',
            'no video could be downloaded. TikTok often refuses anonymous '
            'requests from a datacentre IP -- set AUDITOR_COOKIES_FILE to a '
            'cookies.txt exported from a logged-in browser, or check that '
            'yt-dlp is current (pip install -U yt-dlp).')
    return {
        'downloaded': [str(p) for p in present],
        'failed_urls': failed,
        'seconds': round(time.time() - t0, 2),
    }


def url_for_source(source: str, urls: list[str]) -> Optional[str]:
    """Map a downloaded filename back to the URL that asked for it."""
    stem = Path(source).stem
    for u in urls:
        vid = _video_id(u)
        if vid and stem.startswith(vid):
            return u
    return None


# ---------------------------------------------------------------------------
# Uploaded videos
#
# The alternative to downloading. A frontend that fetches the video itself and
# posts the bytes avoids the one part of this pipeline that fails for reasons
# nothing here controls: TikTok refuses anonymous downloads from datacentre IPs
# far more often than from residential ones, which makes URL ingestion the
# least reliable stage of a deployed run and the hardest to diagnose.
# ---------------------------------------------------------------------------
_UNSAFE_NAME = re.compile(r'[^A-Za-z0-9._-]+')


def safe_upload_name(filename: str, taken: set) -> str:
    """A client-supplied filename reduced to something safe to write.

    Safety is the floor, not the point. `source` on every result row IS the
    filename, and `url_for_source` maps a row back to its original link by
    matching the leading video id -- so a frontend that saves its downloads as
    `<video_id>.mp4` keeps that mapping for free. This therefore PRESERVES the
    name wherever it can instead of generating an opaque one, and only
    rewrites what is unsafe.

    Rejects anything without a video extension rather than guessing: the
    pipeline globs the inbox by suffix, so a file named `clip` is invisible to
    Phase 1 and would fail later as "no video found" instead of here as "that
    is not a video".
    """
    ns = runtime.load()
    raw = Path(filename or '').name          # drop any directory component
    cleaned = _UNSAFE_NAME.sub('_', raw).strip('._')
    p = Path(cleaned or 'video')
    suffix = p.suffix.lower()
    if suffix not in ns['VIDEO_SUFFIXES']:
        raise IngestError(
            'upload',
            f'{(filename or "")[:80]!r} has no recognised video extension. '
            f'Accepted: {", ".join(sorted(ns["VIDEO_SUFFIXES"]))}.')
    base = p.stem[:80] or 'video'
    name = f'{base}{suffix}'
    n = 1
    while name in taken:
        n += 1
        name = f'{base}_{n}{suffix}'
    return name


def validate_video_file(path: Path) -> str:
    """Confirm the bytes are a video, not just the filename.

    An extension is a claim by the caller. `sniff_container` is the notebook's
    own preflight check, reused rather than reimplemented, so an upload is held
    to exactly the standard a downloaded file is. Rejecting here costs one
    request; accepting a non-video means a job that dies in Phase 1 decode with
    an ffmpeg error nobody can read.
    """
    ns = runtime.load()
    if not ns['_is_video'](path.name):
        raise IngestError('upload', f'{path.name!r} is not a video filename')
    kind = ns['sniff_container'](path)
    if not kind:
        raise IngestError(
            'upload',
            f'{path.name!r} does not look like a video file: its first bytes '
            f'match no known container (mp4/mov, matroska/webm, avi, '
            f'mpeg-ts, flv). A partial or re-encoded download does this.')
    return kind


def adopt_uploads() -> dict:
    """The upload equivalent of download_videos: what is actually in the inbox.

    Shaped like `download_videos` so the worker treats both paths identically.
    The files were written and validated by the request that staged them, so
    this only confirms they survived -- the same question fix 56 settled on for
    downloads: ask whether the artifact is there, not whether the call worked.
    """
    ns = runtime.load()
    inbox = ns['DIRS']['inbox']
    present = sorted(p for p in inbox.iterdir()
                     if p.is_file() and ns['_is_video'](p.name)) \
        if inbox.is_dir() else []
    if not present:
        raise IngestError(
            'ingest',
            'no uploaded video survived staging. The files were written to '
            'this job\'s inbox and are gone -- check AUDITOR_DATA_ROOT is a '
            'writable, persistent path and that nothing swept it.')
    log.info('ingest: %d uploaded video(s) in the inbox', len(present))
    return {
        'downloaded': [str(p) for p in present],
        'failed_urls': [],
        'seconds': 0.0,
    }


# ---------------------------------------------------------------------------
# Brief
# ---------------------------------------------------------------------------
def load_brief(*, brief_url: Optional[str] = None,
               brief_text: Optional[str] = None) -> dict:
    """Google Docs URL or raw text -> {text, origin, hash}."""
    ns = runtime.load()
    source = (brief_url or '').strip() or (brief_text or '').strip()
    if not source:
        raise IngestError('brief', 'give either brief_url or brief_text')
    if brief_url and not ns['google_doc_id'](brief_url):
        raise IngestError(
            'brief',
            f'{brief_url[:100]!r} is not a Google Docs URL. This pipeline '
            f'fetches Google Docs only -- share the doc as "anyone with the '
            f'link can view", or send the brief as brief_text.')
    try:
        loaded = ns['load_brief_text'](source, verbose=False)
    except Exception as exc:
        raise IngestError('brief', f'{type(exc).__name__}: {exc}') from exc
    text = loaded['text']
    return {'text': text, 'origin': loaded['source'],
            'hash': ns['sha256_text'](text), 'chars': len(text)}


def compile_brief(text: str, *, runs: int, keep_threshold: float,
                  recompile: bool = False) -> dict:
    """Compile, then FREEZE.

    THE COMPILER IS THE ONE NON-DETERMINISTIC STAGE. The same brief has
    compiled to 6, 9, 16, 21, 22 and 24 requirements across runs at
    temperature 0, and the requirement set is what every verdict is measured
    against -- so instability silently changes what the audit MEANS.

    The notebook resolves this with a human signature (§48b/§48c). An API has
    no human, so the first compile of a given brief text is frozen and every
    later request for that same text reuses it. One brief, one contract. Pass
    recompile=True to replace it deliberately; scores before and after are
    then not comparable, and the response says so.
    """
    ns = runtime.load()
    DIRS = ns['DIRS']
    bh = ns['sha256_text'](text)
    bdir = DIRS['briefs'] / bh
    bdir.mkdir(parents=True, exist_ok=True)

    if not recompile:
        frozen = _frozen_compile(ns, bdir)
        if frozen is not None:
            log.info('brief %s: reusing the frozen compile (%s requirements)',
                     bh[:12], (frozen.get('stats') or {}).get('requirements'))
            frozen['_reused'] = True
            return frozen

    t0 = time.time()
    cfg = ns['replace'](ns['P4'],
                        brief=ns['replace'](ns['P4'].brief, backend='auto'))
    if runs > 1:
        compiled = ns['compile_brief_consensus'](
            text, runs=runs, cfg=cfg, keep_threshold=keep_threshold,
            verbose=False)
    else:
        compiled = ns['compile_brief'](text, cfg, verbose=False)
    if compiled.get('status') != 'OK':
        flags = '; '.join(f'{f.get("code")}: {f.get("detail")}'
                          for f in (compiled.get('flags') or []))
        raise IngestError('brief', f'the brief did not compile: {flags}')

    # FREEZE IT. approved_by names the mechanism, not a person, so an audit
    # trail can always tell an API freeze from a human signature.
    #
    # approved_digest MATTERS, and an earlier version omitted it. An approval
    # without one makes approval_state fall back to "approved without a digest
    # (legacy)" -- which passes, but proves nothing about WHICH requirement
    # set was approved. With the digest, any later change to the requirements
    # invalidates the approval automatically, which is what makes a
    # client-supplied contract safe to accept (see use_precompiled).
    compiled['approved'] = True
    compiled['approved_by'] = 'api:freeze-on-first-compile'
    compiled['approved_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    compiled['approved_digest'] = ns['requirements_digest'](
        compiled.get('requirements') or [])
    key = compiled.get('cache_key') or bh[:16]
    ns['write_json'](bdir / f'requirements__{key}.json', compiled)
    # MOVE THE POINTER. Writing the file is not enough and must not be:
    # selection is by pointer now, precisely so that a compile appearing on
    # disk cannot become the contract by itself. This line is the deliberate
    # act that `recompile=True` exists to perform.
    freeze_pointer(ns, bdir, compiled)
    log.info('brief %s: compiled in %.1fs -> %s requirements (%d run(s), '
             'frozen)', bh[:12], time.time() - t0,
             (compiled.get('stats') or {}).get('requirements'), runs)
    compiled['_reused'] = False
    return compiled


def use_precompiled(compiled: dict,
                    expect_text: Optional[str] = None) -> dict:
    """Accept a compiled brief the CALLER is handing back.

    THE POINT OF THIS IS STATELESSNESS. The frozen compile is the only stored
    thing whose loss changes what a score MEANS -- the compiler is
    non-deterministic (6, 9, 16, 21, 22 and 24 requirements observed from one
    brief at temperature 0), so a recompile silently measures the next video
    against a different contract. It is also about 30 KB. Letting the client
    hold it makes the server stateless without giving up comparability.

    IT IS NOT BLINDLY TRUSTED. The brief is passed through UNCHANGED so that
    `requirements_for_audit` applies the same gate it applies to anything
    else: approval_state() recomputes requirements_digest() and refuses a set
    that has been edited since approval. Forcing `approved = True` here would
    throw that check away -- so it is deliberately not done.
    """
    ns = runtime.load()
    if not isinstance(compiled, dict):
        raise IngestError('brief', 'compiled_brief must be a JSON object -- '
                                   'pass back the `compiled_brief` a previous '
                                   'job returned.')
    if compiled.get('status') != 'OK':
        raise IngestError(
            'brief', f'compiled_brief.status is '
                     f'{compiled.get("status")!r}, not "OK".')
    if not compiled.get('requirements'):
        raise IngestError('brief', 'compiled_brief has no requirements.')

    # If the caller ALSO named the brief, the two must describe the same
    # document. Otherwise the report says it audited brief X against a
    # contract compiled from brief Y, and nothing anywhere contradicts it.
    if expect_text:
        want = ns['sha256_text'](expect_text)
        got = str(compiled.get('brief_hash') or '')
        if got and got != want:
            raise IngestError(
                'brief',
                f'compiled_brief.brief_hash ({got[:12]}) does not match the '
                f'brief you supplied ({want[:12]}). These are two different '
                f'documents; send one or the other, not both.')

    state = ns['approval_state'](compiled)
    if not state.get('approved'):
        raise IngestError(
            'brief',
            f'compiled_brief is not usable: {state.get("reason")}. '
            f'Send it back exactly as the API returned it -- editing the '
            f'requirements invalidates the approval, which is the point.')
    log.info('brief %s: using the caller-supplied contract (%d requirements, '
             '%s)', str(compiled.get('brief_hash'))[:12],
             len(compiled.get('requirements') or []), state.get('reason'))
    out = dict(compiled)
    out['_reused'] = True
    return out


FROZEN_POINTER = 'FROZEN.json'


def _approved_compiles(ns: dict, bdir: Path) -> list:
    """Every approved compile in this brief's directory, oldest first."""
    try:
        paths = sorted(bdir.glob('requirements__*.json'),
                       key=lambda p: p.stat().st_mtime)
    except OSError:
        return []
    out = []
    for p in paths:
        c = ns['read_json'](p)
        if c and c.get('approved') and c.get('status') == 'OK':
            out.append((p, c))
    return out


def freeze_pointer(ns: dict, bdir: Path, compiled: dict) -> None:
    """Record WHICH compile is the contract for this brief."""
    try:
        ns['write_json'](bdir / FROZEN_POINTER, {
            'cache_key': compiled.get('cache_key'),
            'requirements': len(compiled.get('requirements') or []),
            'approved_digest': compiled.get('approved_digest'),
            'frozen_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        })
    except OSError as exc:
        log.warning('could not write the frozen-compile pointer (%s); '
                    'selection falls back to the FIRST approved compile', exc)


def _frozen_compile(ns: dict, bdir: Path) -> Optional[dict]:
    """The contract for this brief -- an explicit choice, not an accident.

    THIS USED TO RETURN THE NEWEST APPROVED COMPILE, which quietly made
    "the first compile is frozen and reused" false. The compiler is
    non-deterministic (20, 27 and 28 requirements observed from one brief),
    so ANY later compile -- a deliberate recompile, a measurement, a second
    process racing the first -- silently became the contract, and every score
    from before it stopped being comparable with every score after, with
    nothing in the output saying so.

    That is exactly the failure the freeze exists to prevent, and it was
    reachable by accident. Measured here: timing a cold compile replaced a
    28-requirement contract with a 27-requirement one, and the next ordinary
    run would have used it.

    Now: FROZEN.json names the active compile. Without it, the OLDEST approved
    compile wins -- "first" as the docstring always claimed -- and the pointer
    is written so the choice is explicit from then on. `recompile=True` is the
    only thing that moves it.
    """
    approved = _approved_compiles(ns, bdir)
    if not approved:
        return None

    try:
        ptr = ns['read_json'](bdir / FROZEN_POINTER) or {}
    except Exception:
        ptr = {}
    want = ptr.get('cache_key')
    if want:
        for _p, c in approved:
            if c.get('cache_key') == want:
                return c
        log.warning('FROZEN.json names %s but no approved compile has that '
                    'key; falling back to the first one', want)

    path, first = approved[0]
    if len(approved) > 1:
        log.info('%d approved compiles for this brief; using the FIRST (%s, '
                 '%d requirements). Later ones exist but do not silently '
                 'become the contract.', len(approved),
                 first.get('cache_key'),
                 len(first.get('requirements') or []))
    freeze_pointer(ns, bdir, first)
    return first


def brief_summary(compiled: dict, origin: str) -> dict:
    """The compiled brief, as the API exposes it."""
    ns = runtime.load()
    st = compiled.get('stats') or {}
    reqs = []
    for r in (compiled.get('requirements') or []):
        reqs.append({
            'requirement_id': r.get('requirement_id') or r.get('id') or '',
            'label': r.get('label') or '',
            'text': r.get('requirement') or r.get('text') or '',
            'type': r.get('type') or '',
            'evidence_mode': r.get('evidence_mode') or '',
            'polarity': r.get('polarity') or 'required',
            'priority': r.get('priority') or 'medium',
            'weight': float(r.get('weight') or 1.0),
            'group_id': r.get('group_id'),
            'group_label': r.get('group_label'),
            'group_mode': r.get('group_mode'),
            'time_window': r.get('time_window'),
        })
    try:
        named = list(ns['named_brief_angles'](compiled) or [])
    except Exception:
        named = []
    flags = compiled.get('flags') or []
    return {
        'brief_hash': compiled.get('brief_hash') or '',
        'origin': origin,
        'status': compiled.get('status') or '',
        'approved': bool(compiled.get('approved')),
        'approved_by': compiled.get('approved_by'),
        'requirements': reqs,
        'scoring_units': int(st.get('scoring_units') or 0),
        'total_weight': float(st.get('total_weight') or 0.0),
        'choice_groups': int(st.get('choice_groups') or 0),
        'named_angles': named,
        'needs_review': list(compiled.get('needs_review') or []),
        'flags': flags,
        'compile_runs': int(compiled.get('runs') or 0),
        'unstable': any('UNSTABLE' in str(f.get('code', '')) for f in flags),
    }
