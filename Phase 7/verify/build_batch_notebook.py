"""Build phases_1_to_7_BATCH.ipynb from the single-video notebook.

WHY A SEPARATE BUILD AND NOT A HAND-EDIT
----------------------------------------
Same discipline as build_notebook.py: the batch notebook is GENERATED, so it
can be regenerated the moment the single-video notebook changes. Hand-editing a
1.9 MB .ipynb is neither reviewable nor repeatable, and a batch notebook that
silently drifts behind the real one is worse than no batch notebook at all.

WHAT IT CHANGES, AND NOTHING ELSE
---------------------------------
1. §0.4  UPLOAD A ZIP OF VIDEOS -- inserted right after §0.3 (paths), because
         everything downstream discovers videos from DIRS['inbox'] and the
         upload has to land before that happens.
2. §48   BRIEF_SOURCE is pointed at the batch brief.
3. §90   THE BATCH RUN -- every video against that one brief, appended at the
         end, reusing every stage function the notebook already defines.
4. §91   Collect the reports into one zip and download it.

Phases 1-3 are ALREADY multi-video (process_all, run_vision_all), so the batch
cell only has to drive Phases 5-7 per video. Phase 4 compiles ONCE: the brief
is cached by its own hash, independent of any video.

The single-video driver cells are left in place deliberately. They run on
whichever video is discovered first and act as a smoke test: if §80 produces a
report, the batch loop will too. Everything is content-addressed, so that work
is reused by the batch rather than repeated.
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(r'C:\Users\Umar Ilyas\creative project')
SRC = ROOT / 'Phase 7' / 'phases_1_to_7_gemini_vision.ipynb'
DST = ROOT / 'Phase 7' / 'phases_1_to_7_BATCH.ipynb'

S = '\u00a7'
EM = '\u2014'

BATCH_BRIEF = ('https://docs.google.com/document/d/'
               '1uWKQMZbOZW_LcEMC5cnFPMfDUTrA19A75JnqzVPzBq8/edit')


def code_cell(src: str) -> dict:
    return {'cell_type': 'code', 'execution_count': None, 'metadata': {},
            'outputs': [], 'source': src.rstrip('\n').splitlines(keepends=True)}


def md_cell(src: str) -> dict:
    return {'cell_type': 'markdown', 'metadata': {},
            'source': src.rstrip('\n').splitlines(keepends=True)}


# ---------------------------------------------------------------------------
# §0.4  the upload, before anything discovers a video
# ---------------------------------------------------------------------------
UPLOAD = f'''# ============================================================================
# {S}0.4  BATCH INPUT  {EM}  PASTE LINKS (below), or upload a .zip
#
# TWO ways in, and the links win: fill VIDEO_URLS a few lines down and the
# notebook fetches them itself. Leave it empty and you get the upload prompt.
#
# This must run BEFORE Phase 1, because every later stage discovers its work
# from DIRS['inbox']. Either way, re-running reuses what is already there
# rather than asking again.
#
# Accepts a .zip of video files, or loose video files. Nested folders are
# fine -- the extractor walks them and flattens. macOS resource forks
# (__MACOSX, ._name) are skipped: they are not videos and ffprobe chokes on
# them with a confusing error.
# ============================================================================
import re
import shutil
import zipfile

# ===========================================================================
# PASTE YOUR VIDEO LINKS HERE  --  one per line, between the triple quotes.
#
# TikTok, or anything else yt-dlp supports. Leave it empty to use the upload
# prompt instead. Downloads are named by the video id, so re-running never
# fetches the same clip twice and the id stays traceable into every report.
# ===========================================================================
VIDEO_URLS = """
""".split()

# TikTok increasingly refuses anonymous downloads. If links fail with an
# extraction or login error, export cookies from a logged-in browser
# (extension: "Get cookies.txt LOCALLY"), upload the file to Colab, and put
# its path here. Left empty = try without cookies, which often still works.
COOKIES_FILE = ''

VIDEO_SUFFIXES = {{'.mp4', '.mov', '.m4v', '.webm', '.mkv', '.avi'}}

# Set to True to clear the inbox first. OFF by default: a batch run that
# silently deletes the videos from a previous run is a bad surprise.
CLEAR_INBOX_FIRST = False


def _is_video(name: str) -> bool:
    p = Path(name)
    if p.name.startswith('._') or '__MACOSX' in name:
        return False
    return p.suffix.lower() in VIDEO_SUFFIXES


def extract_zip_to_inbox(zip_path: Path, verbose: bool = True) -> list:
    """Flatten every video out of a zip into the inbox. Returns the new paths."""
    out = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir() or not _is_video(info.filename):
                continue
            # LOWERCASE THE SUFFIX. preprocess_folder() globs '*.mp4',
            # '*.mov' ... and glob is case-SENSITIVE on Linux, so a file
            # arriving as "clip.MOV" would sit in the inbox, never get a
            # Phase 1 manifest, never appear in discover_videos(), and be
            # silently missing from the batch. Renaming here is the cheapest
            # place to close that.
            _n = Path(info.filename).name
            dest = DIRS['inbox'] / (Path(_n).stem + Path(_n).suffix.lower())
            if dest.exists():
                if verbose:
                    print(f'    already present, keeping: {{dest.name}}')
                out.append(dest)
                continue
            with z.open(info) as fsrc, open(dest, 'wb') as fdst:
                shutil.copyfileobj(fsrc, fdst)
            out.append(dest)
            if verbose:
                print(f'    extracted: {{dest.name}}  '
                      f'({{dest.stat().st_size / 1e6:.1f}} MB)')
    return out


DIRS['inbox'].mkdir(parents=True, exist_ok=True)
if CLEAR_INBOX_FIRST:
    for _f in DIRS['inbox'].iterdir():
        if _f.is_file():
            _f.unlink()
    print('  inbox cleared (CLEAR_INBOX_FIRST = True)')

# ---------------------------------------------------------------------------
# Fetching the links pasted at the top of this cell.
# ---------------------------------------------------------------------------
def _ytdlp():
    """yt-dlp, installed on first use. None if it cannot be had."""
    try:
        import yt_dlp
        return yt_dlp
    except ImportError:
        print('  installing yt-dlp (once per runtime) ...')
        import subprocess
        subprocess.run(['pip', 'install', '-q', '--upgrade', 'yt-dlp'],
                       capture_output=True, timeout=300)
        try:
            import yt_dlp
            return yt_dlp
        except ImportError:
            return None


def download_videos(urls: list, verbose: bool = True) -> list:
    """Fetch each URL into the inbox. Returns the paths that arrived.

    NEVER RAISES, and never stops on the first failure: a private, deleted or
    region-locked link is normal in a list of twenty, and it must cost you
    that one video rather than the whole batch. Every failure is named at the
    end so you can see which link to replace.
    """
    urls = [u.strip() for u in (urls or []) if u.strip().startswith('http')]
    if not urls:
        return []
    mod = _ytdlp()
    if mod is None:
        print('  yt-dlp unavailable -- cannot fetch links. Upload the files '
              'instead.')
        return []
    # Two format strings, tried in order. 'mp4/best[ext=mp4]/best' asks for a
    # progressive mp4 and TikTok does not always offer one -- when it does
    # not, yt-dlp raises rather than taking what is there. Plain 'best' is
    # the fallback, with a browser UA because a default python UA is the
    # easiest thing in the world for a CDN to refuse.
    _UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
           '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
    _FORMATS = ['mp4/best[ext=mp4]/best', 'best']
    got, failed = [], []
    for u in urls:
        # SNAPSHOT THE INBOX, do not trust prepare_filename(). It returns the
        # name yt-dlp INTENDED before any merge or remux, so a file that
        # arrives as .mp4 after a merge can be reported missing and a
        # successful download counted as a failure. Diffing the directory
        # cannot be wrong about what actually landed.
        _before = {{p.name for p in DIRS['inbox'].iterdir() if p.is_file()}}
        _err, _vid = None, ''
        for _fmt in _FORMATS:
            try:
                opts = {{'outtmpl': str(DIRS['inbox'] / '%(id)s.%(ext)s'),
                        'format': _fmt,
                        'quiet': True, 'no_warnings': True, 'noprogress': True,
                        'merge_output_format': 'mp4',
                        'http_headers': {{'User-Agent': _UA}},
                        'retries': 3, 'socket_timeout': 30}}
                if COOKIES_FILE and Path(COOKIES_FILE).exists():
                    opts['cookiefile'] = COOKIES_FILE
                with mod.YoutubeDL(opts) as ydl:
                    _info = ydl.extract_info(u, download=True) or {{}}
                _vid = str(_info.get('id') or '')
                _err = None
                break
            except Exception as exc:
                _err = f'{{type(exc).__name__}}: {{str(exc)[:220]}}'
        _after = {{p.name for p in DIRS['inbox'].iterdir() if p.is_file()}}
        _new = [DIRS['inbox'] / n for n in (_after - _before) if _is_video(n)]
        _had = False
        if not _new and not _vid:
            # Every format raised, so there is no resolved id -- but the clip
            # may still be in the inbox from an earlier run, and a link you
            # already have should not fail just because TikTok started
            # refusing you today. The trailing digits of the URL are the id.
            _m = re.search(r'(\\d{{6,}})(?:\\?|$|/)', u)
            _vid = _m.group(1) if _m else ''
        if not _new and _vid:
            # NOTHING NEW IS NOT THE SAME AS NOTHING THERE. yt-dlp skips a
            # file it already has, so on a re-run it succeeds silently and the
            # directory diff is empty -- which the first version of this read
            # as a failure and reported as "no new file appeared", on three
            # videos that were sitting in the inbox the whole time. The id
            # yt-dlp resolved is the authority: if a video with that id is
            # present, the link is SATISFIED, whoever put it there.
            _new = [DIRS['inbox'] / n for n in sorted(_after)
                    if _is_video(n) and Path(n).stem == _vid]
            _had = bool(_new)
        if _new:
            got.extend(_new)
            if verbose:
                for _p in _new:
                    print(f'  {{"HAVE" if _had else "OK  "}}  {{_p.name:<26}} '
                          f'{{_p.stat().st_size / 1e6:>6.1f}} MB   '
                          f'{{"already in the inbox" if _had else u[:44]}}')
        else:
            failed.append((u, _err or 'yt-dlp reported success but no video '
                                      'with that id is in the inbox'))
            if verbose:
                print(f'  FAIL  {{u}}')
    if failed:
        print()
        print(f'  {{len(failed)}} of {{len(urls)}} link(s) did not download:')
        for u, why in failed:
            print(f'     {{u}}')
            print(f'        {{why}}')
        if len(failed) == len(urls):
            # ALL of them. That is not N unlucky links, it is one cause.
            print()
            print('  EVERY link failed, so this is one cause, not bad luck:')
            print('    - TikTok often needs a login/cookie now. Export cookies')
            print('      from your browser into COOKIES_FILE at the top of')
            print('      THIS cell, or')
            print('    - the runtime cannot reach TikTok, or')
            print('    - yt-dlp is out of date for TikTok\\'s current site.')
            print('      Fix: !pip install -U yt-dlp   then re-run this cell.')
            print('    The full error is printed above -- it names which.')
    return got


# Say which input is in play, ALWAYS. "It asked me to upload instead of
# taking my links" has two causes -- an empty list, or a notebook without
# this feature -- and silence cannot tell them apart.
if VIDEO_URLS:
    print(f'{S}0.4  INPUT = LINKS: fetching {{len(VIDEO_URLS)}} ...')
    _fetched = download_videos(VIDEO_URLS)
    if not _fetched:
        # Falling through to the upload prompt after the links failed looks
        # exactly like "it ignored my links". Say which happened.
        print()
        print('  ' + '!' * 66)
        print('  LINKS WERE GIVEN BUT NOTHING DOWNLOADED. The upload prompt')
        print('  below is the FALLBACK -- your links were tried and failed,')
        print('  for the reason printed above. Upload the files, or fix the')
        print('  cause and re-run this cell.')
        print('  ' + '!' * 66)
    print()
else:
    print(f'{S}0.4  INPUT = UPLOAD: VIDEO_URLS is empty.')
    print('      To use links instead, put them in VIDEO_URLS near the top of')
    print('      THIS cell, between the triple quotes, one per line, then')
    print('      re-run this cell.')

_existing = [f for f in DIRS['inbox'].iterdir()
             if f.is_file() and _is_video(f.name)]
print(f'{S}0.4  inbox holds {{len(_existing)}} video(s) already.')

if _existing:
    print('  Skipping the upload prompt. To add more, set CLEAR_INBOX_FIRST = '
          'True and re-run,')
    print('  or drop files straight into', DIRS['inbox'])
else:
    try:
        from google.colab import files as _colab_files
        print()
        print('  Choose a .zip of your videos (or select the video files '
              'directly).')
        _up = _colab_files.upload()
        for _name, _data in _up.items():
            _tmp = DIRS['inbox'] / _name
            _tmp.write_bytes(_data)
            if _tmp.suffix.lower() == '.zip':
                print(f'  unpacking {{_name}} ...')
                extract_zip_to_inbox(_tmp)
                _tmp.unlink()          # the zip itself is not a video
            elif not _is_video(_name):
                print(f'  ignoring {{_name}} (not a video)')
                _tmp.unlink()
    except ImportError:
        print('  Not on Colab. Put your videos in', DIRS['inbox'],
              'and re-run this cell.')

_videos_in = sorted(f for f in DIRS['inbox'].iterdir()
                    if f.is_file() and _is_video(f.name))
print()
print(f'  READY: {{len(_videos_in)}} video(s) in the inbox')
for _f in _videos_in:
    print(f'    {{_f.name:<52}} {{_f.stat().st_size / 1e6:>7.1f}} MB')
if not _videos_in:
    print('  NOTHING TO DO -- upload some videos before running the rest.')
'''

# ---------------------------------------------------------------------------
# §90  the batch run
# ---------------------------------------------------------------------------
BATCH = f'''# ============================================================================
# {S}90  THE BATCH RUN  {EM}  every video in the inbox, against ONE brief
#
# Phase 4 has already compiled and approved the brief ({S}48 / {S}48c). The brief is
# cached by its own hash and has nothing to do with any video, so it compiles
# ONCE no matter how many videos run.
#
# Phases 1-3 are already multi-video: {S}13.x ran process_all() and {S}30.x ran
# run_vision_all() over everything in the inbox. What is left is Phases 5-7,
# which are per-video, and that is what this loop drives.
#
# EVERYTHING IS CONTENT-ADDRESSED. A video already audited against this brief
# is a cache hit and costs nothing, so re-running this cell after adding two
# more videos only pays for the two.
#
# WHAT IT COSTS: per NEW video, roughly one vision pass (already spent above),
# two batched L3 calls for the requirements, plus the hook, claims, angle and
# standing calls. The brief compile is not repeated.
# ============================================================================

# `time` is NOT imported at module level anywhere in Phases 0-7 -- it is used
# inside functions that import it themselves. A batch cell calling time.time()
# on a fresh kernel would die with NameError, so import it here rather than
# relying on another cell having left it lying around.
import time

# Set True to re-audit videos that already have a score for this brief.
FORCE_REAUDIT = False

# A ceiling, so a mis-clicked 50-video zip cannot spend the afternoon.
MAX_VIDEOS = 25

_batch_t0 = time.time()
BATCH_RESULTS = []          # one row per video, whatever happened
BATCH_FAILURES = []

# unique=True (the default), and it matters twice over.
#
# discover_videos() says it plainly: "Without this, the batch runner would
# process the same video five times and the hand-off could pick a thinned
# variant." §17's sampler ablation writes extra manifests for one video under
# different plan hashes (16-frame, 32-frame, ...), and unique=False returns
# every one of them.
#
# Worse here: §30.5 ran the vision pass over the UNIQUE list, so a thinned
# variant has no visual artifact at all. Auditing it would produce a second,
# blind report for a video that already has a good one.
_all_videos = discover_videos()

# DROP THE NOTEBOOK'S OWN TEST FIXTURE. §18.1 writes its OCR ground-truth clip
# straight into DIRS['inbox'], so Phase 1 gives it a manifest and it arrives
# here looking like a twelfth video -- and gets a transcript, an audit, a score
# and a report, none of which mean anything. One junk row in the table is the
# small harm; the real one is that it would land in the Phase 8 benchmark as a
# labelled case. Excluded by the NAME §18.1 declares, not a guess at it, so
# renaming the fixture cannot silently re-admit it.
_fixture = str(globals().get('TEST_VIDEO_NAME') or 'test_changing_text.mp4')
_dropped = [v for v in _all_videos if v.get('source') == _fixture]
if _dropped:
    _all_videos = [v for v in _all_videos if v.get('source') != _fixture]
    print(f'  skipping {{len(_dropped)}} self-test fixture ({{_fixture}}) '
          f'-- not an audit subject')

if len(_all_videos) > MAX_VIDEOS:
    print(f'  {{len(_all_videos)}} videos found; capping at MAX_VIDEOS='
          f'{{MAX_VIDEOS}}. Raise it deliberately.')
    _all_videos = _all_videos[:MAX_VIDEOS]

print('=' * 78)
print(f'{S}90  BATCH  {EM}  {{len(_all_videos)}} video(s) against '
      f'{{_p6_brief.get("brief_hash", "")[:16]}}')
print('=' * 78)
print(f'  brief   : {{BRIEF_ORIGIN}}')
# Approval is stored TOP-LEVEL on the compiled brief: compiled['approved'] and
# compiled['approved_by']. There is no 'approval' sub-dict -- reading one
# always yielded None and printed "approved: False" on a brief that was in fact
# approved. Harmless in itself, but a false alarm on the one gate that stops an
# unreviewed requirement set being audited is worth getting right:
# requirements_for_audit() REFUSES an unapproved brief, so if the audits below
# run at all, it was approved.
print(f'  requirements: {{len(_p6_brief.get("requirements") or [])}}   '
      f'approved: {{bool(_p6_brief.get("approved"))}}'
      f' by {{_p6_brief.get("approved_by") or "-"}}')
print()

for _n, _v in enumerate(_all_videos, 1):
    _vh = _v['video_hash']
    # discover_videos() returns the filename as 'source' -- there is NO 'path'
    # key, so reading one always fell back to the hash and the whole batch
    # table showed "0257b2b59769" twice instead of naming the video. A
    # reviewer works from filenames; a content hash tells them nothing.
    _name = (_v.get('source') or _v.get('video_id') or _vh[:12])
    print('-' * 78)
    print(f'[{{_n}}/{{len(_all_videos)}}]  {{_name}}   {{_vh[:16]}}')
    print('-' * 78)
    _row = {{'n': _n, 'name': _name, 'video_hash': _vh, 'status': 'ok'}}
    try:
        # ---- Phase 5: evidence, resolved by exact stage key ---------------
        _vd = DIRS['artifacts'] / _vh
        _exp = expected_stage_keys(_v)
        _tr, _, _ = select_artifact(_vd, 'transcript', _exp.get('transcript'))
        _oc, _, _ = select_artifact(_vd, 'ocr', _exp.get('ocr'))
        _vi, _vip, _vih = select_artifact(_vd, 'visual', _exp.get('visual'))
        # "using the newest of 1" means the visual artifact on disk matches no
        # key the CURRENT config accepts -- it was written under a different
        # OOM rung or an older VLM_STAGE_VERSION. With one file per video the
        # fallback picks the right file, so the result stands; what is lost is
        # the guarantee that the vision evidence was produced by the config
        # this report claims. Record it per video instead of letting a warning
        # scroll past.
        _row['visual_stale'] = (_vih not in (_exp.get('visual') or [])
                                and _vih != 'missing')
        _row['visual_missing'] = (_vih == 'missing')
        _ev = build_evidence(_v, _tr, _oc, _vi, P5, verbose=False)
        _recs = load_records(_ev)
        _row['records'] = _ev['stats']['records']

        # ---- WHY a channel cannot support a FAIL -------------------------
        # A requirement lands UNCERTAIN instead of FAIL when can_fail_on() says
        # the modality did not look well enough to assert an absence. That is
        # the single biggest driver of low coverage, and until now it was
        # invisible: seven UNCERTAINs with no stated cause.
        #
        # OCR is marked degraded at unreadable/intervals > 0.5 -- an ACUITY
        # measure. can_fail_on's own doctrine says coverage should gate a FAIL
        # and acuity should not, but only the visual block reports
        # `coverage_degraded`; speech and OCR fall back to the blanket flag.
        # Whether that threshold is right is a question for Phase 8's
        # benchmark, not a guess -- so report the numbers rather than tune them.
        _h = ((_ev.get('stats') or {{}}).get('modality_health')
              or _ev.get('modality_health') or {{}})
        _cf = _ev.get('can_fail_on') or {{}}
        _row['health'] = {{
            k: {{'ran': (_h.get(k) or {{}}).get('ran'),
                'absent': (_h.get(k) or {{}}).get('absent'),
                'degraded': (_h.get(k) or {{}}).get('degraded'),
                'reason': (_h.get(k) or {{}}).get('reason')}}
            for k in ('speech', 'ocr', 'visual') if k in _h}}
        _row['can_fail_on'] = dict(_cf)
        _blocked = [m for m, ok in _cf.items() if ok is False]
        if _blocked:
            print(f'    channels that CANNOT assert an absence: '
                  f'{{", ".join(sorted(_blocked))}}')
            for _k, _hv in (_row['health'] or {{}}).items():
                if _hv.get('degraded') and _hv.get('reason'):
                    print(f'      {{_k}}: {{str(_hv["reason"])[:96]}}')
            print('      -> requirements in those modes become UNCERTAIN, not '
                  'FAIL. That is the')
            print('         gate refusing to assert an absence it did not '
                  'establish.')

        # ---- Phase 6: the audit -------------------------------------------
        _res = audit_video(_v, _ev, _p6_brief, P6, verbose=False,
                           force=FORCE_REAUDIT)
        if _res.get('status') == 'BRIEF_NOT_USABLE':
            raise RuntimeError('brief not usable -- approve it in ' + '{S}48c')
        _row['standing'] = (_res.get('standing') or {{}}).get('standing')
        _ca6 = _res.get('creative_angle') or {{}}
        _row['angle'] = _ca6.get('angle')
        # WHICH of the brief's own concepts this video went with, and the full
        # list the brief offered. Both are already computed per video; nothing
        # aggregates them, so "we offered four concepts and every creator used
        # the same one" is invisible in any single report. That is a finding
        # about the BRIEF, and it only exists across a batch.
        _row['angle_nearest'] = _ca6.get('nearest_brief_concept')
        _row['brief_concepts'] = list(_ca6.get('brief_concepts') or [])
        # The percentage split across the brief's OWN named angles.
        # A description, never a score -- see fix 50.
        _row['named_angles'] = list(_ca6.get('named_angles') or [])
        _row['concept_fit'] = list(_ca6.get('concept_fit') or [])
        # WHICH PATH produced those names: the brief's own sub-headings, or
        # the old group-label fallback. A cached verdicts artifact replays
        # whatever was recorded when it was written, so a stale result and a
        # stale CELL look identical without this.
        _row['angles_source'] = _ca6.get('angles_source') or 'unknown'
        # DID IT MATCH ANY OF THEM? A video can take an angle the brief never
        # listed -- a normal outcome, often a good video -- and that has to be
        # visibly different from "the angle could not be judged".
        _row['off_angle_percent'] = _ca6.get('off_angle_percent')
        _row['matched_named_angle'] = _ca6.get('matched_named_angle')
        # And which item off each MENU she actually took. The group collapse
        # already decided it; this just records the winner per group.
        _chosen = {{}}
        for _v2 in (_res.get('verdicts') or []):
            _sel = next((str(_f) for _f in (_v2.get('flags') or [])
                         if str(_f).startswith('GROUP_SELECTED:')), None)
            if not _sel:
                continue
            _gl = (_v2.get('group_label')
                   or _sel.split(':', 1)[1].split('(')[0].strip())
            _chosen[str(_gl)] = {{
                'option': _v2.get('requirement_label') or _v2.get('requirement_id'),
                'status': _v2.get('status'),
                'alignment': _v2.get('alignment')}}
        _row['chosen_options'] = _chosen

        # ---- Phase 7: score, advice, figures, report ----------------------
        _sc = score_audit(_res, _p6_brief, P7, verbose=False,
                          force=FORCE_REAUDIT)
        _rec = evaluate_recommendations(_res, _p6_brief, _sc, _recs,
                                        cfg=P7, verbose=False)
        _fg = build_figures(_sc, _res, _recs, cfg=P7)
        _rp = write_report(_v, _res, _p6_brief, _sc, _recs, _rec, _fg, P7,
                           verbose=False)

        _s = _sc['score']
        _tp = talking_point_coverage(_res, _p6_brief)
        _row.update({{
            'headline': _s.get('headline'),
            'literal': _s.get('literal_headline'),
            'band': _s.get('status_band'),
            'coverage': _s.get('coverage'),
            'units': _s.get('scoring_units'),
            'credited': _s.get('credited_in_substance'),
            'tp_covered': len(_tp['covered']), 'tp_total': _tp['total'],
            # write_report returns BOTH 'html_path' (the file) and 'html'
            # (the whole 4.5 MB document as a string). The zip step wants the
            # PATH -- Path(<4.5MB of markup>) is not a useful object.
            'report': str((_rp or {{}}).get('html_path') or ''),
            'report_json': str((_rp or {{}}).get('json_path') or ''),
        }})
        # LEAD WITH THE BAND when coverage is thin, exactly as §80 does.
        # Printing the optimistic headline beside a pessimistic band reads as
        # a contradiction -- "86.0 REJECTED" -- when both are correct: 86 is
        # the best case, REJECTED is what the DECIDED half supports. Design
        # rule 6: the grade reads from the established end.
        if _s.get('lead_with_band') and _s.get('band_low') is not None:
            _num = (f'{{_s["band_low"]:.0f}}-{{_s["band_high"]:.0f}}'
                    f'  (graded from the {{_s.get("band_basis", "?")}} end)')
        else:
            _num = f'{{_s.get("headline")}}'
        print(f'  {{_num}}  {{_s.get("status_band")}}   '
              f'{{_s.get("coverage", 0):.0%}} coverage, '
              f'{{_s.get("scoring_units")}} unit(s)   '
              f'standing={{_row["standing"]}}  angle={{_row["angle"]}}')
        if (_s.get('coverage') or 1) < 0.9:
            _unc = _dist_preview = None
            print(f'    {{(1 - (_s.get("coverage") or 0)) * 100:.0f}}% of the '
                  f'weight is UNDECIDED -- the band, not the top of it, is the '
                  f'answer.')
        print(f'  talking points {{_row["tp_covered"]}}/{{_row["tp_total"]}}   '
              f'literal {{_s.get("literal_headline")}} -> credited '
              f'{{_s.get("headline")}}')

        # ---- WHY, when a number needs explaining -------------------------
        # A score of 0 with standing=None is three different situations
        # wearing the same face: a video with no speech that could not be
        # judged, a model call that failed, or a video that genuinely did
        # none of it. The modules already record which -- STANDING_NO_SPEECH
        # vs STANDING_MODEL_FAILED vs a real verdict -- so print it rather
        # than leaving a bare 0.0 REJECTED to be read as a finding.
        from collections import Counter as _Ctr
        _dist = _Ctr(v.get('status') for v in (_res.get('verdicts') or []))
        _row['verdict_mix'] = dict(_dist)
        _sf = [str(f) for f in ((_res.get('standing') or {{}}).get('flags') or [])]
        _af = [str(f) for f in ((_res.get('creative_angle') or {{}}).get('flags') or [])]
        _why = []
        if _row['standing'] is None:
            _why.append('standing NOT judged: '
                        + (', '.join(_sf) if _sf else 'no reason recorded'))
        if _row['angle'] is None:
            _why.append('angle NOT judged: '
                        + (', '.join(_af) if _af else 'no reason recorded'))
        if any('MODEL_FAILED' in f for f in _sf + _af):
            _why.append('A MODEL CALL FAILED -- this is a pipeline problem, '
                        'not a finding about the video.')
            _row['status'] = 'module_failed'
        if _why:
            for _w in _why:
                print(f'    ! {{_w}}')
        print(f'    verdicts: {{dict(_dist)}}')
    except Exception as _exc:
        # One bad video must not cost the other nine. Record and continue.
        _row['status'] = f'{{type(_exc).__name__}}: {{_exc}}'[:200]
        BATCH_FAILURES.append(_row)
        print(f'  FAILED: {{_row["status"]}}')
    BATCH_RESULTS.append(_row)

print()
print('=' * 78)
print(f'BATCH DONE  {{time.time() - _batch_t0:.0f}}s   '
      f'{{sum(1 for r in BATCH_RESULTS if r["status"] == "ok")}} ok, '
      f'{{len(BATCH_FAILURES)}} failed')
print('=' * 78)
'''

SUMMARY = f'''# ============================================================================
# {S}91  THE BATCH TABLE, and one zip to download
#
# The table is the point: one video per row, every number traceable to the
# report beside it. `literal` vs `score` is the paraphrase credit -- how much
# of the score rests on her saying it her own way rather than the brief's.
# ============================================================================
import json
import time

_ok = [r for r in BATCH_RESULTS if r['status'] == 'ok']

print('=' * 100)
print(f'{S}91  BATCH RESULTS  {EM}  {{len(_ok)}} video(s) against '
      f'{{BRIEF_ORIGIN}}')
print('=' * 100)
if _ok:
    print(f'{{"#":<3}}{{"video":<34}}{{"score":>6}}{{"literal":>8}}'
          f'{{"band":>22}}{{"units":>6}}{{"talk":>7}}{{"standing":>11}}')
    print('-' * 100)
    for r in _ok:
        print(f'{{r["n"]:<3}}{{r["name"][:32]:<34}}'
              f'{{r.get("headline", 0) or 0:>6.0f}}'
              f'{{r.get("literal", 0) or 0:>8.0f}}'
              f'{{str(r.get("band", ""))[:20]:>22}}'
              f'{{r.get("units", 0):>6}}'
              f'{{str(r.get("tp_covered", 0)) + "/" + str(r.get("tp_total", 0)):>7}}'
              f'{{str(r.get("standing", ""))[:9]:>11}}')
    print('-' * 100)
    _sc = [r['headline'] for r in _ok if r.get('headline') is not None]
    _li = [r['literal'] for r in _ok if r.get('literal') is not None]
    if _sc:
        print(f'  score   min {{min(_sc):.0f}}  median '
              f'{{sorted(_sc)[len(_sc) // 2]:.0f}}  max {{max(_sc):.0f}}')
    if _li:
        print(f'  literal min {{min(_li):.0f}}  median '
              f'{{sorted(_li)[len(_li) // 2]:.0f}}  max {{max(_li):.0f}}')
        print('  The gap between the two rows IS the paraphrase the brief '
              'allows.')
    from collections import Counter as _C
    print(f'  standing: {{dict(_C(r.get("standing") for r in _ok))}}')
    print(f'  angles  : {{dict(_C(r.get("angle") for r in _ok))}}')

# ---------------------------------------------------------------------------
# WHICH CREATIVE ANGLE DID EACH VIDEO TAKE?
#
# The brief offers a set of concepts; Phase 6 already works out, per video,
# which one it is nearest to. Nothing aggregated it, so the single most useful
# question a creator manager has -- "we offered four concepts, how many did
# anyone actually use?" -- was invisible. It cannot be seen in one report,
# because it is a fact about the BATCH against the BRIEF.
#
# A concept nobody used is reported too. That is the finding: either the
# concept did not land with creators, or the brief did not sell it.
# ---------------------------------------------------------------------------
if _ok:
    _concepts = []
    for r in _ok:                       # identical per video; first wins
        if r.get('brief_concepts'):
            _concepts = list(r['brief_concepts'])
            break
    _by_concept = {{}}
    for r in _ok:
        _by_concept.setdefault(r.get('angle_nearest') or '(none of them)',
                               []).append(r['n'])
    print()
    print('=' * 100)
    print('CREATIVE ANGLES  —  which of the brief\\'s concepts each video took')
    print('=' * 100)
    if _concepts:
        print(f'  the brief offers {{len(_concepts)}} concept(s):')
        for c in _concepts:
            _n = _by_concept.get(c, [])
            _bar = '#' * len(_n)
            print(f'     {{len(_n):2}} video(s)  {{str(c)[:52]:<54}}{{_bar}}'
                  + (f'  {{_n}}' if _n else '   <- nobody used this'))
    else:
        print('  the brief listed no named concepts for the angle read.')
    _unlisted = {{k: v for k, v in _by_concept.items() if k not in _concepts}}
    for k, v in sorted(_unlisted.items(), key=lambda x: -len(x[1])):
        print(f'     {{len(v):2}} video(s)  {{k[:52]:<54}}'
              f'  {{v}}   <- not one of the listed concepts')
    # ---- the brief's OWN named angles, as a percentage split --------------
    # "Which angle is this video, and how much of each" -- per video, then
    # averaged across the batch. A DESCRIPTION: nothing here is scored.
    _named = []
    for r in _ok:
        if r.get('named_angles'):
            _named = list(r['named_angles'])
            break
    if _named:
        print()
        # WHERE THEY CAME FROM. 'document' = the brief's own sub-headings,
        # which is what fix 68 added. 'group_labels' = the old fallback, which
        # reports HOOK LINES on a brief whose angles are sub-headings -- so
        # seeing it here means either §69b was not replaced or these verdicts
        # are a cache hit from before it was. Say which, rather than printing
        # a wrong-looking table with no explanation.
        _src = next((r.get('angles_source') for r in _ok
                     if r.get('angles_source')), 'unknown')
        print(f'  the brief names {{len(_named)}} creative angle(s) '
              f'-- how much of each video belongs to them:')
        if _src != 'document':
            print(f'  !! angles_source = {{_src}} -- these came from the OLD '
                  f'fallback, not the brief\\'s')
            print(f'     sub-headings. Replace {S}69b (cell 127) and re-run '
                  f'{S}90 with FORCE_REAUDIT = True;')
            print(f'     a cached verdicts artifact replays whatever was '
                  f'recorded when it was written.')
        # A COLUMN FOR "NONE OF THEM", but only when some video actually
        # landed there. Without it an off-concept video prints 0% under every
        # named angle -- indistinguishable from a failed measurement, and the
        # one row a creator manager most needs to see.
        _NONE = globals().get('NO_ANGLE_LABEL') or 'none of the listed angles'
        _any_off = any(
            str(x.get('angle')) == _NONE and float(x.get('percent') or 0) > 0
            for r in _ok for x in (r.get('concept_fit') or [])
            if isinstance(x, dict))
        _cols = list(_named[:4]) + ([_NONE] if _any_off else [])
        # A LEGEND, THEN SHORT KEYS. An angle name runs to 40+ characters
        # ("He's Not Ignoring Me... He's Knocked Out"), and a 17-character
        # column turned four distinct angles into four headers all reading
        # "Open concept titl" -- a table whose columns cannot be told apart
        # is not a table. The name is printed once, where it fits.
        _key = {{}}
        print()
        for _i, _a in enumerate(_named[:4], 1):
            _key[_a] = f'A{{_i}}'
            print(f'      A{{_i}}  {{_a}}')
        if _any_off:
            _key[_NONE] = '--'
            print(f'      --  ({{_NONE}})')
        print()
        _hdr = '    {{:<40}}'.format('video')
        for a in _cols:
            _hdr += '{{:>8}}'.format(_key[a])
        print(_hdr)
        _tot, _offc, _nojudge = {{}}, [], []
        for r in _ok:
            _f = {{str(x.get('angle')): float(x.get('percent') or 0)
                  for x in (r.get('concept_fit') or []) if isinstance(x, dict)}}
            _line = '    {{:<40}}'.format(str(r['name'])[:39])
            for a in _cols:
                _p = _f.get(a, 0.0)
                _tot[a] = _tot.get(a, 0.0) + _p
                _line += '{{:>7}}%'.format(f'{{_p:.0f}}')
            print(_line)
            if not _f:
                # NOT the same as "none of these". No split at all means the
                # model failed or returned nothing -- a pipeline problem, and
                # saying "it matched no angle" would be a finding it did not
                # earn.
                _nojudge.append(r['name'])
                print('       -> NOT JUDGED (no split returned) -- a pipeline '
                      'problem, not a finding')
                continue
            _dom = max(_f.items(), key=lambda kv: kv[1])[0]
            if _dom == _NONE:
                _offc.append(r['name'])
                print(f'       -> matched NONE of the brief\\'s angles '
                      f'({{_f[_NONE]:.0f}}%) -- she took her own')
            else:
                print(f'       -> mostly: {{_dom}}')
        print('    ' + '-' * (40 + 8 * len(_cols)))
        _avg = '    {{:<40}}'.format('AVERAGE across the batch')
        for a in _cols:
            _avg += '{{:>7}}%'.format(f'{{_tot.get(a, 0.0) / max(1, len(_ok)):.0f}}')
        print(_avg)
        if _offc:
            print(f'    {{len(_offc)}} of {{len(_ok)}} took an angle the brief '
                  f'never listed: {{_offc[:4]}}')
            print('    That is a fact about the BRIEF\\'s coverage as much as '
                  'about the creators, and')
            print('    it is not a fault: scoring never reads these '
                  'percentages. Check standing and')
            print('    the score to see whether the video still did what was '
                  'asked.')
        if _nojudge:
            print(f'    {{len(_nojudge)}} could NOT be attributed at all: '
                  f'{{_nojudge[:4]}}')
            print('    Different from the line above -- no answer came back, '
                  'so nothing was decided.')
        # "Nobody used X" only blames the brief when the videos were judged.
        # With every video off-concept or unjudged it says nothing useful.
        _unused = [a for a in _named
                   if _tot.get(a, 0.0) <= 0 and len(_nojudge) < len(_ok)]
        if _unused:
            print(f'    NOBODY used: {{_unused}}   <- a fact about the brief, '
                  f'not the creators')
        print('    These percentages DESCRIBE what each creator made. They are '
              'never scored.')

    print()
    print('  by creative angle (what the video IS, from a fixed list in code):')
    _by_angle = {{}}
    for r in _ok:
        _by_angle.setdefault(r.get('angle') or '(not judged)', []).append(r['n'])
    for a, v in sorted(_by_angle.items(), key=lambda x: -len(x[1])):
        print(f'     {{len(v):2}} video(s)  {{a[:52]:<54}}  {{v}}')

    # ---- and which item off each MENU the batch took ----------------------
    _menus = {{}}
    for r in _ok:
        for g, sel in (r.get('chosen_options') or {{}}).items():
            _menus.setdefault(g, {{}}).setdefault(
                str(sel.get('option') or '?'), []).append(r['n'])
    _offered = {{}}
    for _rq in (_p6_brief.get('requirements') or []):
        _g = _rq.get('group')
        if _g:
            _offered.setdefault(_rq.get('group_label') or _g, []).append(
                _rq.get('label') or _rq.get('id'))
    if _menus:
        print()
        print('  WHICH OPTION OFF EACH MENU:')
        for g in sorted(_menus):
            _all = _offered.get(g) or []
            print(f'    {{g}}  ({{len(_all) or "?"}} offered)')
            for opt, ns in sorted(_menus[g].items(), key=lambda x: -len(x[1])):
                print(f'       {{len(ns):2}}  {{opt[:56]:<58}} {{ns}}')
            _unused = [o for o in _all if o not in _menus[g]]
            if _unused:
                print(f'        0  never chosen: {{_unused[:6]}}')

if BATCH_FAILURES:
    print()
    print(f'  {{len(BATCH_FAILURES)}} FAILED -- these produced no report:')
    for r in BATCH_FAILURES:
        print(f'    {{r["name"][:40]:<42}} {{r["status"]}}')

# ---- rows whose NUMBER should not be read as a finding -------------------
# A low score is a finding. A low score the system could not corroborate is
# not -- and the two look identical in a table. design rule 10: two
# independent things must agree, or the system abstains. `standing` IS that
# second read, so a score with no standing has nothing backing it.
_suspect = []
for r in _ok:
    _why = []
    if r.get('standing') is None:
        _why.append('no whole-video read')
    if r.get('angle') is None:
        _why.append('no angle')
    if (r.get('headline') or 0) == 0 and (r.get('literal') or 0) == 0:
        _why.append('scored zero on every unit')
    if _why:
        _suspect.append((r, _why))
_stale = [r for r in _ok if r.get('visual_stale')]
_novis = [r for r in _ok if r.get('visual_missing')]
if _stale or _novis:
    print()
    if _stale:
        print(f'  {{len(_stale)}} of {{len(_ok)}} used a visual artifact that '
              f'matches NO key the current config accepts.')
        print('  It was written under a different OOM rung or an older '
              'VLM_STAGE_VERSION. With one')
        print('  file per video the fallback picks the right file, so these '
              'results stand -- but the')
        print('  vision evidence was not produced by the config this report '
              'names. Re-run §30.5 with')
        print('  force=True before using these for Phase 8 labelling.')
    if _novis:
        print(f'  {{len(_novis)}} have NO visual evidence at all -- those '
              f'reports rest on speech and OCR only.')

if _suspect:
    print()
    print(f'  {{len(_suspect)}} row(s) NEED A HUMAN LOOK before the number is '
          f'quoted:')
    for r, _why in _suspect:
        print(f'    {{r["name"][:34]:<36}} {{r.get("headline")}}  '
              f'{{"; ".join(_why)}}')
        print(f'        verdicts: {{r.get("verdict_mix", {{}})}}')
    print('  A score with no whole-video read has no second opinion behind it.')
    print('  Open those reports before treating the number as a finding.')

# ---- one zip with every report ------------------------------------------
import zipfile as _zf

_out = DIRS['exports'] / f'batch_reports_{{int(time.time())}}.zip'
_out.parent.mkdir(parents=True, exist_ok=True)
_n_added = 0
with _zf.ZipFile(_out, 'w', _zf.ZIP_DEFLATED) as _z:
    for r in _ok:
        _p = Path(r.get('report') or '')
        if _p.exists():
            # Name each report after the VIDEO, not its content hash -- a
            # reviewer works from filenames.
            _z.write(_p, f'{{Path(r["name"]).stem[:48]}}__{{_p.name}}')
            _n_added += 1
    _z.writestr('batch_summary.json', json.dumps(
        {{'brief': BRIEF_ORIGIN,
         'brief_hash': _p6_brief.get('brief_hash', ''),
         'requirements': len(_p6_brief.get('requirements') or []),
         'results': BATCH_RESULTS}}, indent=2))

# ---- WHICH REPORT IS WHICH VIDEO ----------------------------------------
# Reports are written to work/artifacts/<video_hash>/report__<score_key>.html
# -- content-addressed, so neither half of that path names the video. This is
# the only place the three are printed together.
print()
print('=' * 100)
print('  WHICH REPORT IS WHICH VIDEO')
print('=' * 100)
print(f'  {{"video file":<40}}{{"video_hash":<18}}{{"report":<40}}')
print('  ' + '-' * 96)
for r in _ok:
    _rp = Path(r.get('report') or '')
    print(f'  {{str(r["name"])[:38]:<40}}{{str(r["video_hash"])[:16]:<18}}'
          f'{{_rp.name[:38]:<40}}')
print('  ' + '-' * 96)
print('  In the zip below each report is renamed <video file>__report__<key>.html,')
print('  so the filename alone tells you which video it belongs to.')
print(f'  On disk they are at: {{DIRS["artifacts"]}}/<video_hash>/report__<key>.html')

print()
print(f'  {{_n_added}} report(s) + batch_summary.json -> {{_out}}')
print(f'  {{_out.stat().st_size / 1e6:.1f}} MB')

try:
    from google.colab import files as _colab_files
    print('  downloading ...')
    _colab_files.download(str(_out))
except ImportError:
    print('  (not on Colab -- the zip is at the path above)')
'''

BATCH_MD = f'''---

# BATCH MODE {EM} every video against one brief

Everything above is the single-video pipeline, unchanged. It ran on whichever
video was discovered first, which doubles as a smoke test: if {S}80 produced a
report, the batch below will too.

| {S} | what |
|---|---|
| {S}0.4 | upload a `.zip` of videos (runs near the top, before anything looks for a video) |
| {S}90 | audit every video in the inbox against the approved brief |
| {S}91 | the results table, and one zip of every report to download |

**The brief compiles once.** It is cached by its own hash and has nothing to do
with any video, so ten videos cost one compile.

**Every stage is content-addressed**, so re-running {S}90 after adding two more
videos pays only for those two.

**One video failing does not stop the others** {EM} failures are collected and
listed at the end with the reason.
'''


def edit_cell(cells, needle: str, old: str, new: str, label: str) -> None:
    """Replace `old` with `new` in the one cell containing `needle`.

    Fails loudly rather than silently doing nothing: a batch notebook that
    quietly kept a single-video default is exactly the bug this build exists
    to prevent.
    """
    for c in cells:
        if c['cell_type'] != 'code':
            continue
        s = ''.join(c['source'])
        if needle not in s or old not in s:
            continue
        c['source'] = s.replace(old, new, 1).splitlines(keepends=True)
        print(f'  {label}')
        return
    raise SystemExit(f'BATCH EDIT DID NOT MATCH: {label}')


# After Phase 1 has run over the folder, prove that every video in the inbox
# actually produced a manifest. Anything that did not is INVISIBLE to
# discover_videos(), so it would be silently missing from the batch -- a
# nine-video report from a ten-video zip, with nothing saying so.
RECONCILE = f'''
# ---- batch reconciliation: did every uploaded video survive Phase 1? -------
# discover_videos() reads MANIFESTS, not the inbox. A video that failed to
# preprocess is simply absent downstream, so the batch would quietly report on
# nine of your ten videos. Check it here, where it is still cheap to fix.
_inbox = sorted(f for f in DIRS['inbox'].iterdir()
                if f.is_file() and f.suffix.lower() in VIDEO_SUFFIXES)
_have = {{v.get('source') for v in discover_videos()}}
_lost = [f.name for f in _inbox if f.name not in _have]
print()
print(f'  BATCH RECONCILE: {{len(_inbox)}} video(s) in the inbox, '
      f'{{len(_inbox) - len(_lost)}} with a Phase 1 manifest')
if _lost:
    print(f'  {{len(_lost)}} DID NOT PREPROCESS -- they will be missing from the '
          f'batch:')
    for _n in _lost:
        print(f'      {{_n}}')
    print('  Look at the status column above for the reason (corrupt file, '
          'unreadable codec,')
    print('  zero-length upload). Fix or remove them, then re-run this cell.')
else:
    print('  Every video in the inbox is ready for the batch.')
'''


# THE ONE THAT WOULD HAVE RUINED THE BATCH.
#
# run_vision_all() is DEFINED in the notebook and never CALLED. Phase 3 runs
# only through §30.3's run_vision_stage(TARGET, ...) -- a single video. In a
# ten-video batch that leaves nine with no `visual__*.json` at all, so
# build_evidence reports vision as not-run, every visual requirement collapses
# to UNCERTAIN, and the reports come out confidently thin with nothing saying
# why.
#
# The function is already built for exactly this: it loads the backend ONCE,
# loops, and is resumable because a cached video costs nothing. It simply had
# no call site.
VISION_ALL = f'''# ============================================================================
# {S}30.5  BATCH  {EM}  the vision pass for EVERY video
#
# {S}30.3 ran the VLM over TARGET alone. That is the smoke test. This is the
# batch: the same stage over every video that has a Phase 1 manifest.
#
# run_vision_all() loads the model ONCE and then loops, so ten videos cost one
# model load. It is resumable -- a video whose `visual__*.json` already matches
# the current stage key is skipped for free, which is why re-running after
# adding two more videos only pays for the two.
#
# THIS IS THE EXPENSIVE CELL. One vision pass per new video.
# ============================================================================
_vision_videos = discover_videos()

# DROP THE SELF-TEST FIXTURE HERE TOO. §90 already excludes it from the audit,
# but this is the EXPENSIVE cell, and on one real run §18.1's 0.1 MB
# test_changing_text.mp4 spent 240.88s of hosted inference -- more than the two
# real videos combined -- plus a slice of a rate-limited free tier, to describe
# a clip built to prove OCR reads changing text.
_fx = str(globals().get('TEST_VIDEO_NAME') or 'test_changing_text.mp4')
if any(v.get('source') == _fx for v in _vision_videos):
    _vision_videos = [v for v in _vision_videos if v.get('source') != _fx]
    print(f'  skipping the self-test fixture ({{_fx}}) -- not an audit subject')

print(f'{S}30.5  vision pass over {{len(_vision_videos)}} video(s)')
print()

vision_df = run_vision_all(_vision_videos, P3)
print()
print(vision_df.to_string(index=False))

# ---- reconcile: does every video actually HAVE visual evidence now? -------
# A video missing its visual artifact still produces a report -- just one with
# no vision in it. Better to say so here than to let it look like a thin video.
#
# This used to REBUILD the cache key by hand, and got it wrong two ways at
# once: it keyed on the UNRESOLVED P3.vision (the real budget is derived per
# video from its duration and cut count) and it omitted the resolved model the
# writer puts in the key. So it could never match a real filename, and printed
# "N video(s) have NO visual evidence" for EVERY video on EVERY run --
# contradicting, in the same breath, the status column directly above it that
# said OK with 4-11 events each. A check that cannot pass is not a check.
#
# It does not rebuild the key at all now, because it cannot: expected_stage_keys
# is Phase 5's and is not defined yet this early in the notebook. The question
# HERE is only "did the stage produce evidence", which the artifact directory
# and the status column answer between them. Whether that evidence matches the
# current config is a different question, it belongs to the Phase 5 resolver,
# and {S}91 already reports it per row as `visual_stale`.
_novis, _notok = [], []
for _v in _vision_videos:
    _nm = _v.get('source') or _v['video_hash'][:12]
    if not list((DIRS['artifacts'] / _v['video_hash']).glob('visual__*.json')):
        _novis.append(_nm)
_notok = [r for r in vision_df.to_dict('records') if r.get('status') != 'OK']
print()
if _novis:
    print(f'  WARNING: {{len(_novis)}} video(s) have NO visual evidence. Their '
          f'reports will be')
    print('  missing everything the camera showed, and visual requirements '
          'will read UNCERTAIN:')
    for _n in _novis:
        print(f'      {{_n}}')
    print('  Check the status column above before trusting those rows.')

# `if`, NOT `elif`. These are two INDEPENDENT facts: _novis is "no artifact on
# disk at all", _notok is "this run did not end OK". A video that failed today
# but has an artifact from an earlier run is in the second set and not the
# first -- and the elif silently swallowed it. A real run printed
# "1 video(s) have NO visual evidence" with TWO GENERATION_FAILED rows in the
# table directly above. Undercounting missing evidence is the one direction
# this warning must never round.
_also = [_r for _r in _notok
         if (_r.get('source') or '') not in set(_novis)]
if _also:
    print(f'  {{len(_also)}} further video(s) did not end OK this run (an older '
          f'artifact may still be on disk):')
    for _r in _also:
        print(f'      {{_r.get("source", "")}}  {{_r.get("status")}}')
    print('  A stale artifact is not this run\\'s evidence -- §91 reports it '
          'per row as visual_stale.')
if not _novis and not _notok:
    print(f'  All {{len(_vision_videos)}} video(s) have visual evidence.')
'''


# The Phase 2 EXIT CRITERIA cell is scoped to TARGET and runs BEFORE
# process_all() -- so it reports one video, by design ("run all of the above
# across 20 videos, not just this one"). process_all does process everything
# and prints a per-video table, but a failure there is one row among ten and
# easy to scroll past. Same treatment as Phase 1 and Phase 3: say it loudly.
PHASE2_RECONCILE = f'''
# ---- batch reconciliation: ASR + OCR, per video ---------------------------
# The exit-criteria cell above is scoped to TARGET -- one video, deliberately.
# This is the batch view: every video, and anything that failed named outright.
_p2_failed = [r for r in batch.to_dict('records') if r.get('status')]
_p2_ok = [r for r in batch.to_dict('records') if not r.get('status')]
print()
print(f'  BATCH RECONCILE (Phase 2): {{len(_p2_ok)}} of {{len(batch)}} video(s) '
      f'completed ASR + OCR')
for _r in _p2_ok:
    _w = _r.get('words', 0)
    # 0 words is NOT a failure -- a music-only video has no speech, and Phase 5
    # records that as `absent` rather than `degraded`. Flagging it as an error
    # would train you to ignore this line.
    print(f'      {{str(_r.get("source", ""))[:38]:<40}} {{_w:>5}} words'
          + ('   (no speech -- music-only or silent)' if not _w else ''))
if _p2_failed:
    print(f'  {{len(_p2_failed)}} FAILED -- these will have no transcript or OCR, '
          f'so their reports')
    print('  will rest on vision alone:')
    for _r in _p2_failed:
        print(f'      {{str(_r.get("source", ""))[:38]:<40}} {{_r["status"]}}')
else:
    print('  No failures.')
'''


def insert_after(cells, needle: str, src: str, label: str) -> None:
    for i, c in enumerate(cells):
        if c['cell_type'] == 'code' and needle in ''.join(c['source']):
            cells.insert(i + 1, code_cell(src))
            print(f'  {label} (after cell index {i})')
            return
    raise SystemExit(f'BATCH INSERT DID NOT MATCH: {label}')


def main():
    nb = json.loads(SRC.read_text(encoding='utf-8'))
    cells = nb['cells']

    # ---- 1. insert the upload cell straight after §0.3 (paths) -----------
    idx = None
    for i, c in enumerate(cells):
        if c['cell_type'] == 'code' and re.search(
                r'^#\s*\u00a70\.3\b', ''.join(c['source']), re.M):
            idx = i
            break
    if idx is None:
        raise SystemExit('could not find §0.3 (paths) to insert the upload after')
    cells.insert(idx + 1, code_cell(UPLOAD))
    print(f'  §0.4 upload inserted after §0.3 (cell index {idx})')

    # ---- 2. point the brief at the batch document ------------------------
    hits = 0
    for c in cells:
        if c['cell_type'] != 'code':
            continue
        s = ''.join(c['source'])
        if 'BRIEF_SOURCE = ' not in s:
            continue
        # BOTH forms, and for the same reason. §0.3 declares it and wins;
        # §48 keeps a guarded fallback for a kernel where §0.3 never ran.
        # Leaving that fallback pointing at ANOTHER brief means a notebook
        # that silently audits against the wrong campaign the moment someone
        # runs §48 alone -- which is exactly the failure this hoist exists to
        # prevent, reintroduced one cell lower down.
        if "globals().get('BRIEF_SOURCE')" in s:
            new = re.sub(
                r"(BRIEF_SOURCE = globals\(\)\.get\('BRIEF_SOURCE'\) or )'[^']*'",
                lambda m: m.group(1) + f"'{BATCH_BRIEF}'",
                s, count=1)
        else:
            new = re.sub(
                r"^BRIEF_SOURCE = '[^']*'.*$",
                f"BRIEF_SOURCE = '{BATCH_BRIEF}'"
                f"    # BATCH brief -- change THIS line",
                s, count=1, flags=re.M)
        if new != s:
            c['source'] = new.splitlines(keepends=True)
            hits += 1
    if not hits:
        raise SystemExit('could not repoint BRIEF_SOURCE')
    print(f'  BRIEF_SOURCE repointed ({hits} cell) -> {BATCH_BRIEF[:62]}...')

    # ---- 3. the single-video upload must not prompt a SECOND time --------
    edit_cell(
        cells, 'Option A -- upload from your machine',
        'UPLOAD = True    # set False to skip',
        'UPLOAD = False   # BATCH: §0.4 near the top already took the zip.\n'
        '                 # Leaving this True would prompt a second time and\n'
        '                 # then audit only that one file as the smoke test.',
        'single-video upload disabled (§0.4 owns the upload)')

    # ---- 4. Phase 1 must see EVERY video, not just the four default globs -
    # preprocess_folder defaults to ('*.mp4','*.mov','*.webm','*.mkv'). §0.4
    # also accepts .m4v and .avi, and glob is case-sensitive on Linux. A file
    # the extractor accepted but this missed would never get a manifest, never
    # reach discover_videos(), and vanish from the batch without a word.
    edit_cell(
        cells, 'batch_df = preprocess_folder',
        "batch_df = preprocess_folder(DIRS['inbox'])",
        "# BATCH: patterns kept in step with §0.4's VIDEO_SUFFIXES, and both\n"
        "# cases, because glob is case-sensitive on Linux.\n"
        "batch_df = preprocess_folder(\n"
        "    DIRS['inbox'],\n"
        "    patterns=tuple(f'*{s}' for s in sorted(VIDEO_SUFFIXES))\n"
        "             + tuple(f'*{s.upper()}' for s in sorted(VIDEO_SUFFIXES)))",
        'Phase 1 globs every suffix §0.4 accepts, both cases')

    # ---- 5. prove nothing was silently dropped ---------------------------
    for c in cells:
        if c['cell_type'] == 'code' and 'batch_df = preprocess_folder' in \
                ''.join(c['source']):
            c['source'] = (''.join(c['source']).rstrip('\n')
                           + '\n' + RECONCILE).splitlines(keepends=True)
            print('  reconciliation appended after Phase 1')
            break

    # ---- 5b. say loudly how Phase 2 went for EVERY video -----------------
    for c in cells:
        if c['cell_type'] == 'code' and 'batch = process_all(VIDEOS)' in \
                ''.join(c['source']):
            c['source'] = (''.join(c['source']).rstrip('\n')
                           + '\n' + PHASE2_RECONCILE).splitlines(keepends=True)
            print('  Phase 2 per-video reconciliation appended')
            break
    else:
        raise SystemExit('could not find the process_all call site')

    # ---- 6. THE VISION PASS FOR EVERY VIDEO ------------------------------
    # Without this the batch produces ten reports of which nine have no vision.
    insert_after(cells, 'def run_vision_all', VISION_ALL,
                 '§30.5 batch vision pass inserted')

    # ---- 7. append the batch section -------------------------------------
    cells += [md_cell(BATCH_MD), code_cell(BATCH), code_cell(SUMMARY)]

    DST.write_text(json.dumps(nb, ensure_ascii=False, indent=1),
                   encoding='utf-8')

    txt = DST.read_text(encoding='utf-8')
    code = [c for c in cells if c['cell_type'] == 'code']
    moji = {m: txt.count(m) for m in ('\u00c2\u00a7', '\u00e2\u20ac\u201d')
            if txt.count(m)}
    print()
    print(f'  wrote {DST.name}')
    print(f'    {len(cells)} cells ({len(code)} code)')
    print(f'    {DST.stat().st_size / 1e6:.2f} MB')
    print(f'    section signs: {txt.count(S)}   mojibake: {moji or "none"}')


if __name__ == '__main__':
    main()
