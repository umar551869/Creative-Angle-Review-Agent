"""The L3 candidate cap must RE-BALANCE, not slice by rank.

THE BUG THIS PINS
-----------------
`candidates_for` reserves slots per modality on purpose: a video with 165 OCR
fragments and 8 speech turns otherwise offers the adjudicator nothing but
packaging text. On the Biostime video it returned 6 ocr + 4 speech for
"Delicious Fruity Taste".

stage.py then did `cands[:8]`, which takes the top 8 BY RANK -- and the top 8
by cosine are OCR again, so the reserved speech slots fell off the end. The
record that decides the requirement, "plus they love the flavor" at 41.44s, was
one of the two dropped. L3 answered honestly about what it had been shown
("she does not mention the taste in the speech evidence") and produced a FAIL,
three runs in a row, with confidence 1.0.

Nothing in the output could reveal this: the verdict cites the records it was
given, and they are real records. Only comparing what retrieval returned
against what the model received shows it.

This is also the one hand-edit in the generated auditor/ package (the source
notebook is no longer in the repo). If someone regenerates and loses it, this
test is what says so.
"""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from auditor import runtime  # noqa: E402

STAGE = (HERE / 'auditor' / 'audit' / 'stage.py').read_text(encoding='utf-8')


class _Rec:
    """Only what retrieval and the balancer actually read."""

    def __init__(self, rid, modality, t):
        self.id = rid
        self.modality = modality
        self.start_seconds = t
        self.raw_text = f'{modality} text {rid}'
        self.description = ''


def _cands(n_ocr: int, n_speech: int) -> list:
    """Rank order with EVERY ocr record above every speech one.

    That is the real shape: short on-topic OCR fragments outscore a long
    spoken sentence that happens to contain the decisive clause.
    """
    out = [{'record': _Rec(f'ocr{i}', 'ocr', i), 'hint_score': 0}
           for i in range(n_ocr)]
    out += [{'record': _Rec(f'sp{i}', 'speech', 100 + i), 'hint_score': 0}
            for i in range(n_speech)]
    return out


def test_the_slice_is_gone_from_the_source():
    """A rank slice at the L3 cap silently undoes the balancing above it.

    Checked against the CODE, not the whole file: the module docstring quotes
    the old line to explain what changed, and matching that made this test
    fail on its own documentation.
    """
    code = STAGE.split('"""', 2)[-1]
    assert 'escalate.append((rd, cands[' not in code, (
        'stage.py is slicing the balanced candidate list by rank again')
    assert '_balance_modalities(' in code, (
        'the L3 cap must re-balance; see "BALANCE AT THE CAP" in stage.py')


def test_speech_survives_the_l3_cap():
    """The regression, asserted on the balancer itself."""
    ns = runtime.load()
    balance = ns['_balance_modalities']
    cap = ns['P6'].l3.max_candidates_per_requirement
    share = ns['P6'].retrieval.max_modality_share

    kept = balance(_cands(6, 4), cap, share)
    mods = [c['record'].modality for c in kept]
    assert 'speech' in mods, (
        f'no speech record survived the L3 cap of {cap}: {mods}. This is '
        f'exactly the "Delicious Fruity Taste" false FAIL -- the decisive '
        f'spoken line never reaches the adjudicator.')
    assert len(kept) <= cap


def test_a_rank_slice_would_have_dropped_the_decisive_record():
    """Proves the guard can fail -- the old behaviour, asserted.

    A guard that cannot tell the fixed code from the broken code is not a
    guard. The decisive record is the LOWEST-ranked speech one ("plus they
    love the flavor" sat below three other spoken turns), so this compares
    what each strategy does with it specifically, not with speech in general.
    """
    ns = runtime.load()
    cap = ns['P6'].l3.max_candidates_per_requirement
    cands = _cands(6, 4)
    # MEASURED, not invented. candidates_for returned, in rank order:
    #   6 ocr, then speech 0.00s, speech 21.98s, speech 41.44s, speech 31.92s
    # and 41.44s ("plus they love the flavor") is the one that decides it --
    # the THIRD speech record, position 9 of 10.
    decisive = cands[6 + 2]['record'].id

    sliced = [c['record'].id for c in cands[:cap]]
    balanced = [c['record'].id for c in ns['_balance_modalities'](
        cands, cap, ns['P6'].retrieval.max_modality_share)]

    assert decisive not in sliced, (
        f'{decisive} survived a rank slice, so this test no longer '
        f'reproduces the bug it exists to pin')
    assert decisive in balanced, (
        f'{decisive} did not survive re-balancing at the cap -- the fix is '
        f'not working: {balanced}')


@pytest.mark.parametrize('n_ocr,n_speech', [(20, 2), (6, 4), (50, 8), (3, 1)])
def test_every_present_modality_keeps_at_least_one_slot(n_ocr, n_speech):
    ns = runtime.load()
    balance = ns['_balance_modalities']
    kept = balance(_cands(n_ocr, n_speech),
                   ns['P6'].l3.max_candidates_per_requirement,
                   ns['P6'].retrieval.max_modality_share)
    mods = {c['record'].modality for c in kept}
    assert mods == {'ocr', 'speech'}, (
        f'{n_ocr} ocr + {n_speech} speech -> only {mods} reached the judge')


def test_the_stage_version_was_bumped():
    """Design rule: a change to a stage's output bumps its version in the
    same edit, or cached verdicts from before the fix replay forever."""
    cfg = (HERE / 'auditor' / 'audit' / 'config.py').read_text(encoding='utf-8')
    ver = [ln for ln in cfg.splitlines()
           if ln.startswith('VERDICT_STAGE_VERSION')][0]
    major, minor, _ = ver.split("'")[1].split('.')
    assert (int(major), int(minor)) >= (1, 23), (
        f'{ver.strip()} -- the L3 balance change alters verdicts, so the '
        f'stage version must be at least 1.23.0 or every cached verdict from '
        f'before it is served unchanged')
