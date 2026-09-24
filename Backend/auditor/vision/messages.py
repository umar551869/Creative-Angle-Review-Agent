"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 65.
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
def build_context_block(transcript_obj, ocr_obj, cfg: VisionConfig) -> str:
    """
    Transcript + OCR as GROUNDING context.

    plan.md §3.5 calls this a real ablation: context helps the model tie what it
    sees to what was said, but risks it parroting the transcript instead of
    looking. Both switches are in VisionConfig; Phase 9 measures which wins.
    Truncated so context can never crowd the frames out of the budget.
    """
    parts = []
    if cfg.include_transcript and transcript_obj and transcript_obj.get('segments'):
        lines = [f'[{s["start"]:.1f}-{s["end"]:.1f}s] {s["text"].strip()}'
                 for s in transcript_obj['segments']]
        parts.append('SPOKEN (for grounding only -- describe what you SEE):\n'
                     + '\n'.join(lines))
    if cfg.include_ocr and ocr_obj and ocr_obj.get('intervals'):
        # No fixed [:20]. A 3-minute video has far more on-screen text than a
        # 15-second one; the real limit is context_max_chars, which is itself
        # derived from duration. Truncation below is what enforces the budget.
        lines = [f'[{iv["first_seen"]:.1f}-{iv["last_seen"]:.1f}s] {iv["text"]}'
                 for iv in ocr_obj['intervals']]
        parts.append('ON-SCREEN TEXT already read by OCR (do not re-transcribe):\n'
                     + '\n'.join(lines))
    if not parts:
        return ''
    block = '\n\n'.join(parts)
    if len(block) > cfg.context_max_chars:
        block = block[:cfg.context_max_chars] + '\n…(truncated)'
    return block

def build_vlm_messages(frame_table: list, context: str, cfg: VisionConfig) -> list:
    """
    Interleaved [timestamp label][image] pairs, then the instructions.

    Supersedes §17's build_qwen_content(), which was a preview of this shape.
    """
    content = [{'type': 'text', 'text':
                f'This video is represented by {len(frame_table)} sampled frames, '
                f'in chronological order. Each image is preceded by its frame index '
                f'and its time in the video. Refer to frames BY INDEX.'}]
    for row in frame_table:
        content.append({'type': 'text',
                        'text': f'Frame {row["index"]} ({row["timestamp"]:.2f}s):'})
        content.append({'type': 'image'})
    if context:
        content.append({'type': 'text', 'text': context})
    content.append({'type': 'text', 'text': build_p1_instructions(len(frame_table))})
    return [{'role': 'system', 'content': [{'type': 'text', 'text': PROMPT_P1_SYSTEM}]},
            {'role': 'user', 'content': content}]

def estimate_vision_tokens(n_frames: int, max_pixels: int) -> int:
    """Rule of thumb only: ~28x28 source pixels per vision token. §30 measures it."""
    return int(n_frames * max_pixels / 784)

def measure_input_tokens(inputs) -> dict:
    """The REAL token count from the processor output. Never trust the estimate."""
    try:
        ids = inputs['input_ids']
        total = int(ids.shape[-1])
        return {'total_input_tokens': total}
    except Exception:
        return {'total_input_tokens': None}


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 72: print('messages.py loaded')
