"""GENERATED. The order auditor.runtime executes the modules in.

This is the NOTEBOOK CELL ORDER, which is load-bearing: the key is
hoisted above the vision backend, and the vision stage is defined
above the brief compiler. Do not sort this.
"""
LOAD_ORDER = [
    'bootstrap.py',                      # cell 3
    'ingest/video.py',                   # cell 5
    'config.py',                         # cell 6
    'cache.py',                          # cell 7
    'storage/discovery.py',              # cell 8
    'preprocessing/probe.py',            # cell 9
    'preprocessing/preflight.py',        # cell 10
    'preprocessing/sampler.py',          # cell 11
    'preprocessing/scan.py',             # cell 13
    'preprocessing/scenes.py',           # cell 14
    'preprocessing/decode.py',           # cell 15
    'preprocessing/audio.py',            # cell 16
    'preprocessing/manifest.py',         # cell 17
    'pipeline.py',                       # cell 18
    'evidence/text.py',                  # cell 19
    'asr/whisper.py',                    # cell 21
    'ocr/engine.py',                     # cell 22
    'ocr/selection.py',                  # cell 23
    'ocr/run.py',                        # cell 24
    'evidence/dedupe.py',                # cell 25
    'evidence/caption_check.py',         # cell 26
    'pipeline_p2.py',                    # cell 27
    'preprocessing/handoff.py',          # cell 52
    'evaluation/matcher.py',             # cell 53
    'vision/config.py',                  # cell 61
    'vision/schemas.py',                 # cell 62
    'vision/prompts.py',                 # cell 63
    'vision/frames.py',                  # cell 64
    'vision/messages.py',                # cell 65
    'vision/qwen.py',                    # cell 66
    'secrets.py',                        # cell 67
    'vision/gemini.py',                  # cell 68
    'vision/parsing.py',                 # cell 69
    'vision/normalize.py',               # cell 70
    'pipeline_p3.py',                    # cell 72
    'vision/batch.py',                   # cell 84
    'brief/config.py',                   # cell 88
    'brief/loader.py',                   # cell 89
    'brief/schema.py',                   # cell 90
    'brief/temporal.py',                 # cell 91
    'brief/inference.py',                # cell 92
    'brief/structure.py',                # cell 93
    'brief/segmentation.py',             # cell 94
    'brief/prompt.py',                   # cell 95
    'brief/backends.py',                 # cell 96
    'brief/validate.py',                 # cell 97
    'brief/dedupe.py',                   # cell 98
    'brief/compile.py',                  # cell 99
    'brief/approval.py',                 # cell 100
    'evidence5/config.py',               # cell 109
    'evidence5/tolerance.py',            # cell 110
    'evidence5/normalizers.py',          # cell 111
    'evidence5/linking.py',              # cell 112
    'evidence5/health.py',               # cell 113
    'evidence5/aggregates.py',           # cell 114
    'evidence5/stage.py',                # cell 115
    'audit/config.py',                   # cell 120
    'audit/retrieval.py',                # cell 121
    'audit/l1.py',                       # cell 122
    'audit/l2.py',                       # cell 123
    'audit/l3.py',                       # cell 124
    'audit/hook.py',                     # cell 125
    'audit/claims.py',                   # cell 126
    'audit/creative_angle.py',           # cell 127
    'audit/standing.py',                 # cell 128
    'audit/stage.py',                    # cell 129
    'scoring/config.py',                 # cell 137
    'scoring/score.py',                  # cell 139
    'scoring/recommend.py',              # cell 140
    'scoring/report.py',                 # cell 141
    'scoring/figures.py',                # cell 142
]
