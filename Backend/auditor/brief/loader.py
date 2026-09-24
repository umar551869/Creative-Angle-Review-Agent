"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 89.
Regenerate with:  python Backend/tools/extract_from_notebook.py

Bodies are VERBATIM. The only removal is the notebook's driver
statements (the lines that run a stage and print a table); those
are listed at the foot of this file and are replaced by
Backend/app/services/.

This file is LOADED BY auditor.runtime, not imported directly.
The notebook shares one global namespace and binds some names
late (globals().get(...)), so the loader reproduces that exactly
rather than guessing an import graph that the original never had.
"""
GOOGLE_DOC_RE = re.compile(r'docs\.google\.com/document/d/([A-Za-z0-9_-]{16,})')

def google_doc_id(url: str) -> Optional[str]:
    m = GOOGLE_DOC_RE.search(url or '')
    return m.group(1) if m else None

def _looks_like_html(text: str) -> bool:
    head = (text or '')[:800].lstrip().lower()
    return (head.startswith('<!doctype html') or head.startswith('<html')
            or '<meta ' in head or 'accounts.google.com' in head)

def fetch_google_doc(url: str, force: bool = False, verbose: bool = True) -> dict:
    """
    Google Doc -> plain text, cached by document id.

    Returns {'text', 'doc_id', 'source', 'cached', 'chars'}. Raises with an
    actionable message rather than returning something unusable.
    """
    doc_id = google_doc_id(url)
    if not doc_id:
        raise ValueError(f'Not a Google Docs URL: {url[:120]!r}\n'
                         '  Expected .../document/d/<id>/...')
    cache_dir = DIRS['briefs'] / '_docs'
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f'{doc_id}.txt'

    if cache.exists() and not force:
        text = cache.read_text(encoding='utf-8')
        if verbose:
            print(f'  doc cache hit: {doc_id} ({len(text)} chars)')
        return {'text': text, 'doc_id': doc_id, 'source': f'google_doc:{doc_id}',
                'cached': True, 'chars': len(text)}

    export = f'https://docs.google.com/document/d/{doc_id}/export?format=txt'
    try:
        import requests
        r = requests.get(export, timeout=30, allow_redirects=True)
        status, body = r.status_code, r.content.decode('utf-8', errors='replace')
    except ImportError:
        from urllib.request import urlopen
        with urlopen(export, timeout=30) as resp:
            status, body = resp.status, resp.read().decode('utf-8', errors='replace')

    if status != 200:
        raise RuntimeError(
            f'Google Docs returned HTTP {status} for {doc_id}.\n'
            '  Open the doc -> Share -> General access -> "Anyone with the link" (Viewer).')

    # A permission failure comes back as 200 + an HTML sign-in page, NOT an error
    # code. Undetected, that HTML gets compiled as the brief -- and it WOULD
    # produce requirements, which is far worse than failing outright.
    if _looks_like_html(body):
        raise RuntimeError(
            f'Google returned an HTML page instead of the document text for {doc_id}.\n'
            '  That means the doc is not publicly readable.\n'
            '  Fix: Share -> General access -> "Anyone with the link" -> Viewer.\n'
            '  Or: File -> Download -> Plain text, upload it, and pass the file path.')
    if not body.strip():
        raise RuntimeError(f'The document {doc_id} exported as empty text.')

    body = body.replace('\r\n', '\n').replace('\r', '\n').lstrip('﻿')
    cache.write_text(body, encoding='utf-8')
    if verbose:
        print(f'  fetched Google Doc {doc_id}: {len(body)} chars -> {cache.name}')
    return {'text': body, 'doc_id': doc_id, 'source': f'google_doc:{doc_id}',
            'cached': False, 'chars': len(body)}

def load_brief_text(source: str, force: bool = False, verbose: bool = True) -> dict:
    """Accepts a Docs URL, a local file path, or raw brief text. Always returns text."""
    s = (source or '').strip()
    if not s:
        raise ValueError('load_brief_text got nothing')
    if google_doc_id(s):
        return fetch_google_doc(s, force=force, verbose=verbose)
    if s.lower().startswith(('http://', 'https://')):
        raise ValueError(
            f'Only Google Docs URLs are fetched directly. Got: {s[:90]}\n'
            '  Download the brief as plain text and pass the file path instead.')
    p = Path(s)
    if len(s) < 400 and p.exists() and p.is_file():
        text = p.read_text(encoding='utf-8', errors='replace')
        if verbose:
            print(f'  loaded {p.name}: {len(text)} chars')
        return {'text': text, 'doc_id': None, 'source': f'file:{p.name}',
                'cached': False, 'chars': len(text)}
    return {'text': s, 'doc_id': None, 'source': 'inline', 'cached': False, 'chars': len(s)}


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 97: print('§37b brief loader ready: Google Docs URL | file path | raw text')
