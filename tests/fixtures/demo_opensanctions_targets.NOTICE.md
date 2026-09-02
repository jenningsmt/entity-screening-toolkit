# NOTICE — `demo_opensanctions_targets.csv`

This file is a **modified, filtered subset** of OpenSanctions' consolidated
`targets.simple.csv` export, provided under the CC BY-NC 4.0 license terms
described below. This notice exists to satisfy that license's "indicate
changes" condition — see `docs/data_sources.md`'s OpenSanctions entry for
the full license/attribution statement.

- **Source:** OpenSanctions (opensanctions.org), consolidated
  `targets.simple.csv` export.
- **Downloaded from:** `https://data.opensanctions.org/datasets/latest/default/targets.simple.csv`
  (redirected to a dated snapshot artifact at download time).
- **Downloaded on:** 2026-09-02.
- **Real, full source file:** 1,221,948 rows, ~455MB.
- **What was selected, and how:** a deterministic pseudorandom sample of
  3,000 rows (Python `random.seed(20260902)`, uniform without replacement
  over the full row set), plus the 7 real "Seven Sons of National Defence"
  university entries (already independently verified present in the real
  file by `tests/test_screening_seven_sons.py`) added back in if the random
  draw didn't already include them — all 7 were confirmed present in the
  real file at curation time. Final file: 3,007 rows.
- **What was NOT changed:** every row kept every original column, verbatim,
  from the real source file. No field was edited, redacted, or invented.
- **Why a subset, not the full file:** the full 455MB file is far larger
  than a git-tracked fixture should be, and Section 9 of
  `docs/requirements.md` already calls for "a curated demo slice," not the
  full live pipeline, for exactly this reason (see also
  `demo_nsf_awards.json`'s NSF Award Search provenance in
  `docs/data_sources.md`, built the same way).
- **License:** CC BY-NC 4.0 (see `docs/data_sources.md` and
  <https://creativecommons.org/licenses/by-nc/4.0/>). Non-commercial
  redistribution of a modified subset, with attribution and this
  changes-indicated notice, is permitted under that license's own terms.
