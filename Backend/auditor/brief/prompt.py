"""GENERATED from phases_1_to_7_BATCH.ipynb -- do not edit by hand.

Source: code cell(s) 95.
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
PROMPT_P4_SYSTEM = (
    'You convert marketing briefs into machine-checkable requirements. '
    'You output JSON only -- no prose, no markdown fences, no commentary. '
    'You never judge a video; you only restate what the brief asks for.'
)

PROMPT_P4_INSTRUCTIONS = textwrap.dedent(f"""
    Convert the BRIEF below into atomic, checkable requirements.

    The brief is a DOCUMENT with headings. Read each heading before its lines:

      "Purpose" / "Overview" / "About" / "Summary"
          Background. Produces NO requirements. A video cannot satisfy
          "this guide helps creators develop high-performing content".

      "Options" / "Samples" / "Examples" / "Concepts" / "Hooks" / "Ideas"
          CHOICES, not a checklist. The creator picks ONE.

          Emit ONE REQUIREMENT PER ITEM, every one of them carrying the SAME
          "group" string and "group_mode": "one_of". Twelve hook options become
          TWELVE requirements in one group. NEVER collapse them into a single
          "use one of the approved hooks".

          Give every member the SAME "group_intent": one sentence saying what
          KIND of ask these options are examples of. Not a summary of the list --
          the ask behind it. For twelve hooks about hair damage that might be
          "Open by naming a hair problem the viewer recognises and creating
          enough doubt that they keep watching."

          The intent MUST name the OBSERVABLE THING, not just where it goes.
          Alignment is judged against this sentence, so an intent that names
          only a position matches anything in that position. "Conclude the
          video with a call to action" matches ANY closing sentence, including
          a product claim -- write "Ask the viewer to take a specific next
          step: follow, comment, click the link, or buy" instead. A group_intent
          that would still be true of a video that never did the thing is
          wrong. Name the act, the words, or the object to look for.

          This matters more than it looks. The auditor scores how CLOSELY a
          creator aligned, and a creator who writes her own hook in the right
          spirit has done what you asked. Without the intent, the requirement
          reads as a demand for one exact sentence and her version scores zero.

          This is not padding, and it is not optional:
            * the auditor matches the creator's words against each option's OWN
              text. An option you did not write down cannot be checked, and a
              collapsed requirement can only ever come back UNCERTAIN.
            * the scorer already treats a one_of group as ONE unit, so listing
              the options separately does not inflate anything.

          Getting the GROUP wrong is the opposite mistake, and just as bad: it
          fails a video for the eleven options it did not pick.

      "Benefits" / "Claims" / "Ingredients" / "Results" / "Talking points"
          Things the creator MAY say, not must. Produce NO requirement for them
          individually. If they carry figures ("27% reduction", "within 21
          days"), emit ONE forbidden requirement saying any figure stated must
          match those, with claim_classes ["unsupported_outcome"].

      "Requirements" / "Must" / "Do" / "Don't" / "Rules" / "Guidelines"
          Ordinary requirements. group null, group_mode "all_of".

    SPLIT compound asks. "Show the product and say the name" is TWO requirements.
    Do not split a single ask that merely lists targets: "mention hydration and
    barrier support" may stay as one requirement with both in match_hints, or be
    split into two -- either is acceptable, but never split "show X and say X".
    Never split the items of a one_of group apart from their group.

    Return EXACTLY this JSON shape:

    {{"campaign": "<name if the brief states one, else null>",
      "requirements": [
        {{"requirement": "<one imperative sentence>",
          "type": "<one of: {' | '.join(REQUIREMENT_TYPES)}>",
          "evidence_mode": "<one of: {' | '.join(EVIDENCE_MODES)}>",
          "polarity": "<required | forbidden>",
          "priority": "<low | medium | high | critical>",
          "machine_checkable": true,
          "group": "<null, or a shared id for items that are ALTERNATIVES>",
          "group_mode": "<all_of | one_of | any_of>",
          "group_label": "<the heading the choice came from, else \\"\\">",
          "group_intent": "<for an ALTERNATIVES item: one sentence naming what
                            KIND of ask these options are examples of, and the
                            OBSERVABLE THING to look for -- not only where in
                            the video it belongs. Identical for every member of
                            the group. Empty otherwise.>",
          "deadline_seconds": null,
          "window_start_expr": null,
          "window_end_expr": null,
          "match_hints": ["<lexical variants a transcript or caption might use>"],
          "acceptance_criteria": ["<what would make this pass, in plain words>"],
          "claim_classes": [],
          "brief_span": "<the exact sentence of the brief this came from>"
        }}
      ]}}

    EVIDENCE MODE is the field that matters most. It decides which channel can
    satisfy the requirement:
      speech_only        the words must be SPOKEN. On-screen text does NOT satisfy it.
      visual_only        it must be SEEN happening.
      ocr_only           it must appear as on-screen TEXT.
      speech_or_text     spoken OR on-screen text -- either satisfies.
      visual_and_speech  both, together.
      any                any channel counts. Use this for forbidden/policy rules,
                         because a prohibited claim is just as bad written as spoken.

    Worked examples -- these two differ ONLY in the verb:
      "Show 20% OFF"  -> speech_or_text  (a caption reading "20% OFF" satisfies it)
      "Say 20% OFF"   -> speech_only     (the same caption does NOT satisfy it)
      "Show the product" -> visual_only  (a caption reading "product" satisfies nothing)

    TIMING:
      "within the first 5 seconds"  -> deadline_seconds: 5
      "in the opening"              -> window_start_expr: "0", window_end_expr: "3"
      "end with" / "in the last 5s" -> window_start_expr: "duration - 5",
                                       window_end_expr:   "duration"
      Windows relative to the END must use the literal word `duration`. NEVER write
      an absolute number for an end-relative window: the same brief is run against
      videos of different lengths and a hardcoded number is wrong for all but one.
      Expressions may use only: numbers, `duration`, + - * / and parentheses.

    FORBIDDEN requirements ("do not make medical claims") set polarity "forbidden"
    and list the detectable classes in claim_classes, from:
      {' | '.join(CLAIM_CLASSES)}

    VAGUE requirements ("make it feel premium") are still emitted, with
    machine_checkable false. Do not invent an observable for them.

    COMPLETENESS. Every line of a requirements section, and every ITEM of an
    alternatives section, must produce a requirement. Before you answer, count
    the items in each alternatives section and check you emitted that many. A
    brief listing 12 hooks and 5 calls to action yields at least 17 requirements
    from those two sections alone.

    Produce between 1 and {{max_req}} requirements. "Do not pad" means do not
    INVENT: every requirement must trace to text actually in the brief, and
    brief_span must quote it. It does NOT mean keep the list short -- dropping an
    option the brief lists is an error, not restraint.

    BRIEF:
    ---
    {{brief}}
    ---
    JSON only:
""").strip()

PROMPT_P4_REPAIR = textwrap.dedent("""
    Your previous reply could not be used:

    {errors}

    Return the SAME requirements, corrected, in the exact JSON shape requested.
    JSON only -- no fences, no commentary.
""").strip()

def build_brief_prompt(brief_text: str, cfg: BriefConfig) -> str:
    return PROMPT_P4_INSTRUCTIONS.replace('{max_req}', str(cfg.max_requirements)) \
                                 .replace('{brief}', (brief_text or '').strip())


# --------------------------------------------------------------------------
# DRIVER STATEMENTS REMOVED (they belong to app/services, not the library):
#   line 166: print('§41 prompt loaded.')
#   line 167: print(f'  version   : {BRIEF_PROMPT_VERSION}')
#   line 168: print(f'  length    : {len(PROMPT_P4_INSTRUCTIONS)} chars (~{len(PROMPT_P4_I
