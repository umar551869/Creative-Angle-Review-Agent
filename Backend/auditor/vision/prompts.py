"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 63.
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
PROMPT_P1_SYSTEM = (
    'You are a precise visual observer for a video auditing system. '
    'You report only what is visibly present. You never evaluate, rate, or judge.'
)

PROMPT_P1_INSTRUCTIONS = """\
TASK
Describe the observable events in this video, using the numbered frames above.

RULES
1. Report ONLY what is visible. Do not infer intent, quality, or effectiveness.
2. Do NOT judge compliance. Do not say whether anything is good, strong, weak,
   correct, required, or meets any brief. That is another system's job.
3. Refer to time ONLY by frame index. Never write seconds -- the frame labels are
   there so you can cite indices, and indices are the only timing you may report.
   VALID INDICES FOR THIS VIDEO ARE {first_index} TO {last_index} INCLUSIVE.
   Never write a number outside that range, not even to mean "until the end":
   an event that runs to the end of the video has frame_end = {last_index}.
4. BE SPECIFIC ABOUT WHAT IS DIFFERENT. Report each distinct thing you observe.
   If one action continues across many frames you may report it as a single
   event spanning them, OR as the stages you can actually tell apart -- both are
   acceptable, because consecutive near-identical events are combined later. So
   never withhold a detail to keep the list short: if the product is raised
   overhead, turned to show a label, or set down, that is worth recording.
   What is NOT wanted is the same sentence repeated with nothing new in it.
5. BE EXACT ABOUT WHAT IS DONE WITH THE PRODUCT. `product_held` means it is only
   being held or shown. If it is opened, squeezed, poured, applied to skin or
   hair, rubbed in, or otherwise used, report the matching type and action verb
   instead. "held" and "applied" are different facts and are never interchangeable.
6. REPORT VISUAL CALLS TO ACTION. If a button, arrow, swipe-up graphic, pointing
   gesture toward a link, or similar prompt appears, report it as `cta_visual`.
   Report a block of on-screen text as `text_overlay`. Another system reads WHAT
   the text says; you report THAT it is present and what kind of thing it is.
7. WRITE EVERY DESCRIPTION IN ENGLISH, whatever language is spoken in the video
   or printed on screen. Quote on-screen words in their original language if you
   need to name them, but the description around them must be English.
8. If you are unsure, lower `confidence`. Do not guess and do not invent events.
9. If the product identity is unclear, describe what you see ("a white tube")
   rather than naming a brand you cannot read.

EVENT TYPES -- use exactly one of these strings:
{event_types}

ACTION VERBS -- for product events, use exactly one of these, or null:
{action_verbs}

OUTPUT
Return ONE JSON object and nothing else. No prose, no markdown fences.

{{
  "events": [
    {{
      "frame_start": 0,
      "frame_end": 3,
      "type": "person_speaking_to_camera",
      "action": null,
      "description": "A person faces the camera and begins speaking.",
      "objects": ["person"],
      "confidence": 0.9
    }},
    {{
      "frame_start": 7,
      "frame_end": 11,
      "type": "product_applied",
      "action": "applied",
      "description": "A white tube is squeezed and the contents spread on a hand.",
      "objects": ["white tube", "hand"],
      "confidence": 0.8
    }}
  ]
}}

Cover the whole video, from the first frame to the last. Prefer a specific
observation over a vague one, and never merge two genuinely different actions
into a single event to save space.
"""

PROMPT_P1_REPAIR = """\
Your previous reply could not be parsed as JSON.

Error: {error}

Reply again with ONE valid JSON object and nothing else -- no prose, no markdown
fences, no trailing commas. Same schema as before.
"""

def build_p1_instructions(n_frames: int = 0) -> str:
    """
    n_frames states the VALID INDEX RANGE in the prompt itself.

    Without it the model over-runs the end: on a 12-frame video it asked for
    frame 12 to mean "until the end", the normaliser clamped to 11, and the
    event silently acquired the last frame's timestamp. Harmless when the
    over-run is one frame; on a long video an index 13 past the end pins the
    event to the end of the video and manufactures evidence for exactly the
    end-of-video requirements a brief cares about.
    """
    last = max(0, int(n_frames) - 1)
    return PROMPT_P1_INSTRUCTIONS.format(
        event_types=', '.join(EVENT_TYPES),
        action_verbs=', '.join(ACTION_VERBS) + ', null',
        first_index=0,
        last_index=last,
    )


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 112: print(f'prompts loaded  --  {PROMPT_VERSION}, {len(build_p1_instructions())}
