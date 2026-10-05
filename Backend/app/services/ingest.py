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
    """The id a TikTok link's download is named by.

    `/video/<digits>` FIRST. The original looked only for a run of six or more
    digits ending at `?`, `/` or the end, and so read the HANDLE of
    `tiktok.com/@jane1234567/video/7671…` as the video id -- the file that then
    arrived was named for the real id, matched nothing, and a good link was
    reported as "could not download". The same anchor also survives
    `…/video/<id>#x` and `…/video/<id>&a=1`, which the old pattern missed.
    The trailing-digits rule stays as the fallback for other link shapes.
    """
    u = url or ''
    m = re.search(r'/(?:video|photo|v)/(\d{6,})', u)
    if not m:
        m = re.search(r'(\d{6,})(?:\?|#|&|$|/)', u)
    return m.group(1) if m else ''


def resolve_short_link(url: str) -> str:
    """vm.tiktok.com/XXXX and tiktok.com/t/XXXX carry no video id, so nothing
    downstream can tell which downloaded file they became -- and with parallel
    downloads, "the first file in the inbox" is some other link's video.
    Follow the redirect once to the canonical /video/<id> URL. Any failure
    returns the link unchanged; the download then decides.
    """
    if _video_id(url):
        return url
    try:
        import requests
        r = requests.get(url, allow_redirects=True, timeout=15, stream=True,
                         headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; '
                                  'Win64; x64) AppleWebKit/537.36 (KHTML, like '
                                  'Gecko) Chrome/124.0 Safari/537.36'})
        r.close()
        return r.url if _video_id(r.url) else url
    except Exception as exc:
        log.warning('could not resolve %s: %s', url[:60], exc)
        return url


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

    resolved = {u: resolve_short_link(u) for u in urls}

    # ONE DOWNLOAD PER VIDEO, however many links point at it. The same video
    # sent as `…/video/123` and `…/video/123?lang=en` is one file, named by
    # its id. Fetched twice in parallel, the two workers write the same file
    # and whichever looks first finds it half-written, so a good link was
    # logged "could not download" -- measured on a live job, not supposed.
    # The first link of each video is fetched; the rest share its outcome.
    leader: dict[str, str] = {}              # video id -> the link fetched
    for u in urls:
        leader.setdefault(_video_id(resolved[u]) or u, u)
    to_fetch = list(dict.fromkeys(leader.values()))

    def _fetch(url: str) -> tuple[str, Optional[Path]]:
        target = resolved[url]
        try:
            ns['download_videos']([target], verbose=False)
        except Exception as exc:                 # it should not raise; belt
            log.warning('download raised for %s: %s', url[:60], exc)
        vid = _video_id(target)
        hit = next((p for p in sorted(inbox.iterdir())
                    if p.is_file() and ns['_is_video'](p.name)
                    and (not vid or p.stem.startswith(vid))), None)
        return url, hit

    pairs = run_parallel(to_fetch, _fetch, workers=workers,
                         label='download',
                         on_error=lambda u, e: (u, None))
    got = {u: hit for u, hit in pairs}
    failed = [u for u in urls
              if got.get(leader[_video_id(resolved[u]) or u]) is None]
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
        # original link -> the link actually fetched (differs only for short
        # links), so a result can be named by the link the caller sent.
        'resolved': {u: t for u, t in resolved.items() if t != u},
        'seconds': round(time.time() - t0, 2),
    }


def url_for_source(source: str, urls: list[str],
                   resolved: Optional[dict] = None) -> Optional[str]:
    """Map a downloaded filename back to the URL that asked for it -- the
    caller's own link, even when it was a short link that had to be resolved.
    """
    stem = Path(source).stem
    for u in urls:
        vid = _video_id((resolved or {}).get(u) or u)
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
_DOC_TAB = re.compile(r'[?&#]tab=(t\.[A-Za-z0-9]+)')


def doc_tab(url: str) -> str:
    """The `tab=t.xxxx` a Google Docs link points at, or ''."""
    m = _DOC_TAB.search(url or '')
    return m.group(1) if m else ''


def fetch_google_doc_tab(url: str) -> dict:
    """One Google Doc, ONE TAB of it when the link names a tab, as plain text.

    A brand with two focus products keeps both briefs in one document, a tab
    each. The notebook's loader asks for `export?format=txt` with no tab, and
    Google answers with every tab concatenated -- so two products' concepts
    arrive as one brief and a video is judged against angles that were never
    its brief. Passing `tab=` exports that tab alone.

    FETCHED FRESH, unlike the notebook's loader, which caches a document by id
    for ever. Briefs get edited between campaigns and a stale copy audits
    against a brief nobody is using any more; the fetch is one small request.
    """
    ns = runtime.load()
    doc_id = ns['google_doc_id'](url)
    tab = doc_tab(url)
    body = _export_doc_text(ns, doc_id, tab)
    # AN UNKNOWN TAB IS NOT AN ERROR TO GOOGLE. Asked for a tab id that does
    # not exist, it answers 200 with the FIRST tab -- measured, not assumed --
    # so a mistyped or deleted tab would audit one product's videos against
    # the other product's brief with nothing anywhere saying so. The first tab
    # is `t.0`; any other tab that comes back identical to it was not found.
    if tab and tab != 't.0' and body == _export_doc_text(ns, doc_id, 't.0'):
        raise RuntimeError(
            f'The document {doc_id} has no tab {tab!r}: Google returned its '
            f'first tab instead. Open the brief, click the tab you mean, and '
            f'copy the link again.')
    return {'text': body,
            'source': f'google_doc:{doc_id}' + (f'#{tab}' if tab else '')}


def _export_doc_text(ns: dict, doc_id: str, tab: str = '') -> str:
    """Plain text of a Google Doc (one tab of it, when given), or raise."""
    import requests
    export = f'https://docs.google.com/document/d/{doc_id}/export?format=txt'
    if tab:
        export += f'&tab={tab}'
    where = f'{doc_id}{" tab " + tab if tab else ""}'
    last: Optional[Exception] = None
    for attempt in (1, 2):                # one retry: a blip must not cost a job
        try:
            r = requests.get(export, timeout=30, allow_redirects=True)
        except requests.RequestException as exc:
            last = exc
            time.sleep(2)
            continue
        if r.status_code >= 500 and attempt == 1:
            time.sleep(2)
            continue
        body = r.content.decode('utf-8', errors='replace')
        if r.status_code != 200:
            raise RuntimeError(
                f'Google Docs returned HTTP {r.status_code} for {where}. Open '
                f'the doc -> Share -> General access -> "Anyone with the '
                f'link" (Viewer).')
        # A permission failure is a 200 with an HTML sign-in page, which
        # WOULD compile into real-looking requirements. The notebook's guard.
        if ns['_looks_like_html'](body):
            raise RuntimeError(
                f'Google returned an HTML page instead of the text of '
                f'{doc_id}. The doc is not publicly readable: Share -> '
                f'General access -> "Anyone with the link" -> Viewer.')
        body = body.replace('\r\n', '\n').replace('\r', '\n').lstrip('﻿')
        if not body.strip():
            raise RuntimeError(f'The document {where} exported as empty text.')
        return body
    raise RuntimeError(f'could not reach Google Docs for {where}: {last}')


_CONCEPT_TITLE = re.compile(r'^[\s*\-•]*\d+\.\s+\S')
# The headings that end the concept list. WHOLE-LINE for "Hooks", and an
# apostrophe required in "Do's" / "Don'ts": the first version matched any line
# that merely BEGAN with these letters, so a detail line "Does the creator show
# it?" ended the list and the concepts after it were lost.
_SECTION_STOP = re.compile(
    r'^(hooks?(\s+concepts?)?|key talking points\b.*|call to actions?\b.*|'
    r'do[’\']s\b.*|don[’\']ts\b.*|product links?\b.*|'
    r'best performing videos\b.*|deliverables\b.*|requirements\b.*|'
    r'posting requirements\b.*|guidelines\b.*|mandatories\b.*|'
    r'timeline\b.*|compensation\b.*)\s*:?\s*$', re.I)


def _is_section_stop(line: str) -> bool:
    """A HEADING that ends the concepts -- short and not a sentence."""
    s = re.sub(r'^[\s*\-•]+', '', line or '').strip()
    return (0 < len(s) <= 90 and s[-1] not in '.?!,;'
            and bool(_SECTION_STOP.match(s)))


def _plain(s: str) -> str:
    """A concept name reduced to what identifies it: no quotes, bullets,
    numbering or case, so `1. “Visual hook”(Top…)` and `Visual hook (Top…)`
    are the same name."""
    s = re.sub(r'^[\s*\-•]*(\d+\.)?\s*', '', s or '')
    s = re.sub(r'["“”‘’\']', '', s)
    return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()


def _concept_detail(text: str, name: str) -> list[str]:
    """What the brief says under one concept: the lines between its title and
    the next concept or section. This is what the angle judge reads to decide
    whether a video followed it, so a name alone is not enough."""
    want = _plain(name)
    lines = [ln.strip() for ln in (text or '').splitlines()]
    out: list[str] = []
    for i, ln in enumerate(lines):
        if not ln or _plain(ln) != want:
            continue
        for nxt in lines[i + 1:]:
            if not nxt:
                continue
            if _CONCEPT_TITLE.match(nxt) or _is_section_stop(nxt):
                break
            out.append(re.sub(r'^[\s*\-•]+', '', nxt).strip())
        break
    return [x for x in out if x][:6]


_CONCEPT_NUMBERED = re.compile(r'^[\s*\-•]*(\d+)\.\s+(.+?)\s*:?\s*$')
_CONCEPTS_HEADING = re.compile(r'^creative concepts?\s*:?$', re.I)
_PURPOSE_HEADING = re.compile(r'^purpose\s*:?$', re.I)


def clean_angle_name(name: str) -> str:
    """A concept title as a category name: the quote marks around it removed,
    a parenthetical set off by a space. `“Visual hook”(Top performing angle)`
    -> `Visual hook (Top performing angle)`."""
    n = re.sub(r'["“”]', '', name or '')
    n = re.sub(r'(?<=\S)\(', ' (', n)
    return re.sub(r'\s+', ' ', n).strip()


def document_angles(text: str) -> list[str]:
    """The brief's creative concepts, read from its own numbered list.

    Every brief this pipeline is given has the same spine: Purpose, then the
    creative concepts as NUMBERED TITLES (under a "Creative Concepts" heading,
    usually), then Hooks, Key talking points, Call to action. So the concepts
    are the numbered titles between the opening and the first of those later
    headings -- and that is all this reads.

    It is deliberately narrower than the notebook's reader, which also accepts
    unnumbered and bolded shapes and, on real briefs, got four of eleven wrong
    (see use_given_angles). Returns [] for a brief not shaped this way, and
    the caller then falls back to the notebook's reader.

    THREE THINGS KEEP IT FROM READING SOMETHING ELSE AS A CONCEPT:
      * it starts at the "Creative Concepts" heading when the brief has one,
        and only falls back to "Purpose" when it does not -- so a numbered
        list inside the Purpose is not mistaken for the concepts;
      * it stops at the next section heading (see _is_section_stop);
      * it stops when the numbering RESTARTS at 1. Concepts are one list,
        numbered once; a second "1." is a different list, under a heading
        this does not know by name.
    """
    lines = [ln.strip() for ln in (text or '').replace('﻿', '').splitlines()]
    lines = [ln for ln in lines if ln]
    start = _CONCEPTS_HEADING if any(_CONCEPTS_HEADING.match(ln) for ln in lines) \
        else _PURPOSE_HEADING
    out: list[str] = []
    on = False
    for s in lines:
        if not on:
            on = bool(start.match(s))
            continue
        if _is_section_stop(s):
            break
        m = _CONCEPT_NUMBERED.match(s)
        if not m:
            continue
        if int(m.group(1)) == 1 and out:
            break
        name = clean_angle_name(m.group(2))
        # A title, not a numbered sentence of prose.
        if 2 <= len(name) <= 90 and any(c.isalpha() for c in name) \
                and name.lower() not in (x.lower() for x in out):
            out.append(name)
    return out[:12]


def settle_angles(compiled: dict, text: str,
                  given: Optional[list[str]] = None) -> str:
    """Decide, once, which angle names this brief is judged against.

    The caller's list if it sent one; else the document's own numbered
    concepts; else whatever the notebook's reader makes of it. Returns which
    it was -- 'given', 'document' or 'notebook' -- so a job can SAY where its
    category names came from instead of leaving it to be assumed.
    """
    if given and any(str(a or '').strip() for a in given):
        use_given_angles(compiled, given, text=text)
        return 'given'
    doc = document_angles(text)
    if doc:
        use_given_angles(compiled, doc, text=text)
        return 'document'
    # A compile handed back by a client may still carry the list an EARLIER job
    # settled on. Left in place it would be used while this job reports
    # 'notebook'. Drop it, and the cache-key suffix that went with it.
    if compiled.pop('given_angles', None) is not None:
        compiled['cache_key'] = str(
            compiled.get('cache_key') or '').split('+angles:')[0]
    return 'notebook'


def use_given_angles(compiled: dict, angles: Optional[list[str]],
                     text: str = '') -> dict:
    """Judge against the angle names the CALLER gives, not ones read back out
    of the document.

    The notebook finds a brief's angles by reading its "Creative Concepts"
    section, and on real briefs that is wrong often enough to matter. Checked
    against eleven: a concept typed as `* 1. Title` was taken for a bullet and
    dropped; `Tired Day Fix!` was dropped for ending like a sentence; a brief
    with no "Creative Concepts" heading yielded no angles at all; and a
    "Key talking points" heading was reported as an angle. Each of those files
    a video under the wrong category, or under none.

    The hub already stores the angle list for every brief -- they ARE its
    categories -- so it sends them, and they are used exactly as sent. That
    also means a category can never be spelled two ways.

    The reader is wrapped once, in the namespace the pipeline resolves it from,
    rather than edited: auditor/ is generated from the notebook, and a brief
    with no given angles still takes the notebook's path untouched.
    """
    given = list(dict.fromkeys(
        str(a).strip() for a in (angles or []) if str(a or '').strip()))
    if not given:
        return compiled
    ns = runtime.load()
    orig = ns['brief_angle_blocks']
    if not getattr(orig, '_given_aware', False):
        def brief_angle_blocks(c: dict, limit: int = 8) -> list:
            names = (c or {}).get('given_angles')
            if not names:
                return orig(c, limit=limit)
            text = (c or {}).get('brief_text') or ''
            return [{'name': n, 'detail': _concept_detail(text, n)}
                    for n in names]
        brief_angle_blocks._given_aware = True
        ns['brief_angle_blocks'] = brief_angle_blocks
    compiled['given_angles'] = given
    if text and not compiled.get('brief_text'):
        compiled['brief_text'] = text      # where each concept's detail is read
    # A different angle list is a different question. The verdict cache is
    # keyed on the compile's cache_key, so fold the list in or a cached audit
    # against the OLD list answers for the new one.
    tag = ns['sha256_text']('\n'.join(given))[:12]
    base = str(compiled.get('cache_key') or '').split('+angles:')[0]
    compiled['cache_key'] = f'{base}+angles:{tag}'
    return compiled


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
        loaded = (fetch_google_doc_tab(source) if brief_url
                  else ns['load_brief_text'](source, verbose=False))
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
