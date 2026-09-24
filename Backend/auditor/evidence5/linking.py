"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 112.
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
def _text_similar(a: str, b: str, min_ratio: int) -> bool:
    """Do two strings look like the same caption? rapidfuzz when present."""
    a, b = (a or '').strip().lower(), (b or '').strip().lower()
    if not a or not b:
        return False
    try:
        from rapidfuzz import fuzz
        return fuzz.token_set_ratio(a, b) >= min_ratio
    except Exception:
        pass
    try:
        ta, tb = set(content_tokens(a)), set(content_tokens(b))
    except Exception:
        ta = set(re.findall(r'[a-z0-9]{3,}', a))
        tb = set(re.findall(r'[a-z0-9]{3,}', b))
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= (min_ratio / 100.0)

def _quoted_span(desc: str) -> str:
    """
    The text a VLM description QUOTES, if any.

    Phase 3 asks the describer to report that on-screen text exists, not what it
    says -- but it may quote words to name them. A quote is a real claim about
    the string and can be matched; the surrounding description cannot.
    """
    if not desc:
        return ''
    best = ''
    for m in re.finditer(r'["\u201c\u2018\']([^"\u201d\u2019\']{3,})'
                         r'["\u201d\u2019\']', desc):
        if len(m.group(1)) > len(best):
            best = m.group(1)
    return best.strip()

def link_text_overlays(records: list, cfg: EvidenceConfig = None) -> list:
    """
    A VLM text_overlay and an OCR interval at the same time are ONE caption.

    Linked rather than merged: they carry different things worth keeping. Double
    counting them would let a single caption satisfy a requirement twice and
    inflate any coverage measure built on record counts.
    """
    cfg = cfg or P5.evidence
    flags = []
    overlays = [r for r in records if r.modality == 'visual' and r.type == 'text_overlay']
    texts = [r for r in records if r.modality == 'ocr']
    for ov in overlays:
        # A VLM text_overlay DESCRIBES on-screen text; it does not transcribe it.
        # Phase 3's prompt says so outright -- "Another system reads WHAT the
        # text says; you report THAT it is present" -- so the description reads
        # "a caption appears at the top of the frame" while the OCR reads "Your
        # hair looks so healthy and shiny!". Comparing them scores near zero,
        # and the similarity gate then blocks a link that is plainly correct.
        #
        # The prompt does allow QUOTING ("quote on-screen words if you need to
        # name them"), so when the description quotes something, that quote is
        # a real signal and is compared. When it does not, time is all we have,
        # and time is enough: the flag this sets means "do not count this twice",
        # which is true of every caption inside the overlay's span.
        _quoted = _quoted_span(ov.description)
        for oc in texts:
            gap = max(ov.start_seconds, oc.start_seconds) - min(ov.end_seconds, oc.end_seconds)
            if gap > cfg.link_overlap_seconds:
                continue
            if _quoted and oc.raw_text and not _text_similar(
                    _quoted, oc.raw_text, cfg.link_text_min_ratio):
                continue
            if oc.id not in ov.linked_ids:
                ov.linked_ids.append(oc.id)
            if ov.id not in oc.linked_ids:
                oc.linked_ids.append(ov.id)
            if 'SAME_PHENOMENON_AS_OCR' not in ov.flags:
                ov.flags.append('SAME_PHENOMENON_AS_OCR')
            flags.append({'code': 'LINKED_TEXT_OVERLAY',
                          'detail': f'{ov.id} <-> {oc.id}: "{oc.raw_text[:40]}"'})
    return flags

def merge_visual_intervals(records: list, cfg: EvidenceConfig = None) -> tuple:
    """
    (records, flags). Same-type visual events closer than merge_gap become one
    interval. LOSSLESS: every constituent is kept in merged_from, and every
    description is kept in the flags, because two fragments of one holding can
    still describe different facts.
    """
    cfg = cfg or P5.evidence
    vis = sorted([r for r in records if r.modality == 'visual'],
                 key=lambda r: (r.type, r.start_seconds))
    others = [r for r in records if r.modality != 'visual']
    # Needed to repair back-references when a LINKED record is absorbed below.
    _by_id = {x.id: x for x in records}
    out, flags = [], []
    cur = None
    for r in vis:
        if cur is not None and r.type == cur.type and \
                r.start_seconds - cur.end_seconds <= cfg.merge_gap_seconds:
            cur.end_seconds = max(cur.end_seconds, r.end_seconds)
            cur.merged_from.append(r.id)
            cur.frame_ids = list(dict.fromkeys(cur.frame_ids + r.frame_ids))
            cur.timestamp_unreliable = cur.timestamp_unreliable or r.timestamp_unreliable
            cur.is_approximate_ts = cur.is_approximate_ts or r.is_approximate_ts
            # the merged interval ENDS where the absorbed record ends, so it
            # inherits that record's end tolerance, not the wider of the two
            cur.end_tolerance_seconds = r.end_tolerance_seconds
            cur.time_tolerance_seconds = max(cur.start_tolerance_seconds,
                                             cur.end_tolerance_seconds)
            # Carry the absorbed record's RELATIONSHIPS too. Dropping its
            # linked_ids orphans a cross-modal link, and dropping its ACTION
            # verb loses it from demonstration_intervals -- a merge of
            # "held" and "applied" would report only "held", which is exactly
            # the visual/demonstration distinction plan.md §35 exists for.
            for lid in r.linked_ids:
                if lid not in cur.linked_ids:
                    cur.linked_ids.append(lid)
                # A LINK HAS TWO ENDS, and r is about to stop existing.
                #
                # Carrying r's links onto cur fixed the forward direction and
                # left the far end naming a record that is no longer in the
                # output: cur -> X held while X -> cur did not. Phase 5's
                # 'every link is mutual' criterion caught it on the first video
                # where a linked record was also merged.
                _peer = _by_id.get(lid)
                if _peer is not None:
                    _peer.linked_ids = list(dict.fromkeys(
                        cur.id if _x == r.id else _x for _x in _peer.linked_ids))
            for f in r.flags:
                if f.startswith(('ACTION:', 'OBJECTS:')) and f not in cur.flags:
                    cur.flags.append(f)
            if r.description and r.description not in cur.description:
                # keep the other fact, do not discard it for being shorter
                cur.flags.append(f'ALSO:{r.description[:70]}')
            if r.confidence is not None:
                cur.confidence = max(cur.confidence or 0.0, r.confidence)
            cur.confidence_kind = 'derived'
            flags.append({'code': 'MERGED_VISUAL_INTERVAL',
                          'detail': f'{r.id} into {cur.id} ({cur.type})'})
            continue
        cur = r
        out.append(cur)
    return others + out, flags


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 151: print('§55 linking and merging loaded.')
