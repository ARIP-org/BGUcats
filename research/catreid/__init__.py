"""Cat re-identification research track (phase 1b).

Deliberately standalone: this package imports nothing from `src/`, touches no
AWS service, and can be reviewed or discarded without affecting the collection
pipeline. See CLAUDE.md, "Research track".

Module layout mirrors the order the pipeline runs in:

    records   the common (image, identity, session) shape everything speaks
    splits    session-aware and held-out-identity splitting
    metrics   top-k, BAKS, BAUS, per-identity breakdown
    datasets  adapters over wildlife-datasets
    embed     MegaDescriptor feature extraction (needs torch)
    evaluate  the harness that ties them together

`records`, `splits` and `metrics` are pure — numpy at most — so the evaluation
logic is unit-testable without downloading a single weight.
"""
