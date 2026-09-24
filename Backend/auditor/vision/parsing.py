"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 69.
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
def extract_json_object(text: str) -> Optional[str]:
    """
    Find the outermost {...} in a reply, respecting string literals and escapes.

    A naive find('{')/rfind('}') breaks the moment a description contains a brace,
    and models do produce those. Returns None when there is no balanced object.
    """
    if not text:
        return None
    s = text.strip()
    # strip markdown fences if the whole reply is fenced
    if s.startswith('```'):
        s = re.sub(r'^```[a-zA-Z]*\s*', '', s)
        s = re.sub(r'\s*```$', '', s).strip()
    start = s.find('{')
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None          # unbalanced -> almost always truncated output

def parse_model_json(text: str) -> tuple:
    """
    Returns (obj_or_None, error_or_None, method).
    method: 'direct' | 'extracted' | 'repaired' | 'failed'
    """
    if not text or not text.strip():
        return None, 'empty model output', 'failed'

    try:                                            # 1. already valid
        return json.loads(text), None, 'direct'
    except Exception:
        pass

    candidate = extract_json_object(text)           # 2. brace-matched
    if candidate:
        try:
            return json.loads(candidate), None, 'extracted'
        except Exception:
            pass

    try:                                            # 3. json_repair
        import json_repair
        obj = json_repair.loads(candidate if candidate else text)
        if isinstance(obj, (dict, list)) and obj:
            return obj, None, 'repaired'
        return None, 'json_repair produced nothing usable', 'failed'
    except ImportError:
        return None, 'unparseable and json_repair is not installed', 'failed'
    except Exception as exc:
        return None, f'{type(exc).__name__}: {str(exc)[:120]}', 'failed'

def looks_non_english(text: str) -> bool:
    """
    Cheap check that a description is in English.

    This exists because EVERY downstream word list is English -- JUDGMENT_WORDS,
    STOPWORDS, CONTINUATION_WORDS. If the model describes a Spanish video in
    Spanish, the merge gate just merges less (harmless), but the judgment scan
    matches nothing and §32's "NO judgment language" PASSES VACUOUSLY. A silent
    pass on a correctness check is worse than a failure, so make it visible.

    The prompt (rule 7) tells the model to answer in English regardless of the
    video's language. This catches the case where it does not obey.

    Two signals, either is enough:
      - a non-Latin script (Chinese, Arabic, Hindi, Cyrillic, ...)
      - a sentence long enough to need function words that contains none
        ("Una persona sostiene el recipiente blanco" has no English stopword)
    """
    if not text or not text.strip():
        return False
    letters = [c for c in text if c.isalpha()]
    if letters and sum(1 for c in letters if ord(c) > 127) / len(letters) > 0.15:
        return True
    words = re.findall(r"[A-Za-z']+", text.lower())
    if len(words) >= 6 and not any(w in STOPWORDS for w in words):
        return True
    return False

def detect_judgment_language(text: str) -> list:
    """
    Pass 1 must not judge. Returns the judgment words found in a description.

    Checked rather than trusted: the prompt says 'do not judge', and §32 verifies
    the model actually obeyed. A leak here means the phase boundary broke.

    Matched on WORD boundaries, never as substrings. 'should' is inside
    'shoulder', and a hair-care video says 'shoulder' constantly -- measured on
    a live run, "the woman holds the white jar near her shoulder" was reported
    as judgment leakage and blocked the Phase 3 exit criteria on a pass where
    the model had obeyed the prompt exactly.

    Lookarounds rather than \\b: the list holds a hyphen ('non-compliant'), a
    trailing space ('must ') and multi-word phrases, and \\b cannot close a
    match after punctuation.
    """
    low = f' {(text or "").lower()} '
    found = []
    for w in JUDGMENT_WORDS:
        t = w.strip()
        if t and re.search(rf'(?<!\w){re.escape(t)}(?!\w)', low):
            found.append(w)
    return found


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 131: print('parsing.py loaded')
