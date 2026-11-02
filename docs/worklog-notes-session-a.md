# Raw worklog notes — session A (coordinator: data layer, metrics, deploy)

Factual log kept as the work happened. This is source material for `docs/WORKLOG.md`, which
the candidate writes.

## How the work was split
- **Session A** (this one): profiling, Bronze/Silver/Gold, metric layer, reconciliation,
  deployment, docs. It also coordinated session B.
- **Session B** (`openbi-take-home-ca`): API, auth, access control, frontend. Handed off with a
  written contract (`docs/CONTRACT.md`) and plan (`docs/plans/02-session-b-app.md`), plus a real
  `Scope` type committed *before* hand-off so both sides import one definition.
- Session B was given work only after the contract existed. Its output was **reviewed, not
  trusted**: I re-ran the suite (65 pass), read `security.py`/`auth.py`/`db.py`, and re-tested
  bypass attempts over real HTTP in prod mode.

## Mistakes caught (agent errors, with how they were caught)

1. **False data finding in the plan.** At planning time the agent reported "event_seq and
   changed_at disagree for 60 applications" as if it were an ordering conflict. It was an
   artefact of the profiling script: Python's stable sort on identical timestamps kept file
   order. **Caught** when the DuckDB check with `ORDER BY ts, seq` showed zero disagreements;
   the real finding is 60 *timestamp ties*, which `event_seq` resolves (chain check: 0 breaks).
   **Change:** findings now need a second, independent query before they go in a doc.
2. **Silent row loss in Gold.** `fact_interview` used an INNER JOIN to `fact_application` and
   came out at 1,275 vs 1,284 rows. Nothing errored. **Caught** by eyeballing the row-count
   print-out of the first pipeline run. Cause: 9 interviews reference non-existent applications.
   **Change:** LEFT JOIN plus an `application_missing` flag, and a permanent test
   (`test_no_rows_silently_dropped`) comparing Silver vs Gold counts for every fact.
3. **Raw data mutated by git config.** The agent added `* text=auto eol=lf`, which would have
   rewritten the CRLF line endings of the raw CSVs in the repository. That breaks "Bronze = as
   landed" and changes the file fingerprint. **Caught** from git's CRLF→LF warnings on the
   data commit. **Change:** `northbeam_ats_pack/** -text`, re-added, and verified with
   `git ls-files --eol`.
4. **Numbers written from memory into the reconciliation note.** The first draft said 131
   corrected salaries, duplicate ids from C00573 and 53 people without applications. Querying
   the warehouse gave **111**, **C00561** and **52**. **Change:** every number in
   RECONCILIATION.md was re-queried before commit.
5. **"Docker build passed" was false.** The background build reported exit 0, but that was
   `tail`'s exit code; the Docker daemon wasn't running. **Caught** when `docker run` failed.
   **Change:** prod-mode verification was done via uvicorn + curl instead, and the README says
   plainly that the image build is unverified locally.
6. DuckDB 2.0 API drift (`relation.fetchone()` removed, `->` lambdas deprecated): the agent
   wrote pre-2.0 idioms twice. This was caught by the errors, so it's minor.

## Decisions that were NOT delegated blindly (verified against the data)
- **Person identity = phone, not email.** Testing both ways gave email 574, union 533, phone
  560. Phone was chosen because of the evidence pattern in the duplicate records, not because
  it matched the control.
- **51.25 vs 51.2.** I refused to tune. I checked for a data cause (re-applications, date
  anomalies) before calling it rounding.
- **Orphans kept as `req_key = -1`**, not dropped.

## Prompting changes made during the build
- After mistake 1: "verify any data claim with a second query before writing it down".
- After mistake 2: "print row counts per layer on every run; any drop must be explained".
- Gave session B a negative list (what must *not* appear in `app/`/`frontend/`), backed by a
  test, rather than just "don't duplicate metrics".
