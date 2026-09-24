"""Every function the orchestrator needs must exist in the loaded namespace.

This is the extraction's acceptance test. A cell dropped from CELL_MAP, or a
definition mis-classified as a driver, shows up here as a missing name rather
than as an AttributeError twelve minutes into a job.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from auditor import runtime  # noqa: E402

REQUIRED = {
    'Phase 0  ingestion': [
        'download_videos', 'extract_zip_to_inbox', 'VIDEO_SUFFIXES'],
    'shared    cache': [
        'stage_key', 'read_json', 'write_json', 'sha256_file',
        'canonical_json'],
    'Phase 1  preprocess': [
        'preprocess_video', 'preprocess_folder', 'discover_videos',
        'probe_video', 'build_manifest', 'CFG'],
    'Phase 2  asr/ocr': [
        'load_asr', 'run_asr_stage', 'load_ocr', 'run_ocr_stage',
        'process_all', 'P2'],
    'Phase 3  vision': [
        'make_vision_backend', 'run_vision_stage', 'run_vision_all',
        'visual_evidence_for', 'autoselect_vision_model',
        'probe_vision_models', 'P3'],
    'Phase 4  brief': [
        'load_brief_text', 'fetch_google_doc', 'google_doc_id',
        'compile_brief', 'compile_brief_consensus', 'load_compiled_brief',
        'approval_state', 'requirements_for_audit', 'sha256_text',
        'parse_brief_sections', 'P4'],
    'Phase 5  evidence': [
        'build_evidence', 'load_records', 'expected_stage_keys',
        'select_artifact', 'modality_health', 'can_fail_on', 'P5'],
    'Phase 6  verdicts': [
        'audit_video', 'evaluate_requirements', 'evaluate_hook',
        'evaluate_claims', 'evaluate_standing', 'named_brief_angles',
        'P6'],
    'Phase 7  score/report': [
        'score_audit', 'evaluate_recommendations', 'build_figures',
        'write_report', 'talking_point_coverage', 'P7'],
}


def main() -> int:
    ns = runtime.load()
    missing, ok = [], 0
    for group, names in REQUIRED.items():
        print(f'\n  {group}')
        for name in names:
            present = name in ns and ns[name] is not None
            ok += present
            if not present:
                missing.append(name)
            print(f'      {"OK " if present else "MISSING"}  {name}')
    total = sum(len(v) for v in REQUIRED.values())
    print(f'\n  {ok}/{total} entry points present')

    # The creative angle is the newest feature and the easiest to lose.
    ca = [n for n in ns if 'angle' in n.lower() or 'concept_fit' in n.lower()]
    print(f'  creative-angle names: {sorted(ca)}')
    if missing:
        print(f'\n  MISSING: {missing}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
