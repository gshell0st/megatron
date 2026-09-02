"""Per-target retest history: a JSON snapshot on every recon/scan job,
a deterministic diff against the previous one ("beyond compare"), and a
lightweight retrieval step that feeds that history back into the next
Claude triage call as grounding context. See snapshot.py, diff.py, context.py.
"""
