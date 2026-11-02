# Reconciliation note — Gold vs CONTROL_TOTALS.txt

All five figures are produced by the metric layer (`metrics/definitions.py`) reading Gold, and
pinned by `tests/test_pipeline_controls.py`. Nothing below was tuned to match: each rule was
chosen from what the data shows, then the figure was checked.

| # | Control | Control figure | Gold figure | Ties? |
|---|---|---|---|---|
| 1 | Unique people in candidate pool | 560 | **560** | Yes |
| 2 | Applications at Offer, close of 2026-03-31 | 32 | **32** | Yes |
| 3 | Median time to hire (hires 2026-01-01 → 06-30), days | 58 | **58** (97 hires) | Yes |
| 4 | Total annual offered salary, Engineering, INR | 200,700,000 | **200,700,000** (110 offers) | Yes |
| 5 | Offer acceptance rate, % | 51.2 | **51.25** (164 / 320) | Yes, see rounding note |

Global rule from the control file: *exclude any record that cannot be tied to a valid
requisition*. 23 applications reference `REQ-2xxx` ids that are not in `requisitions.json`.
They are kept in Gold (`req_key = -1`, `is_orphan = true`) so they stay auditable, and every
metric filters them out.

---

## 1. Unique people — 560

**The trap:** the file has 601 candidate *records*. People appear more than once.

| Rule | Result |
|---|---|
| Count records | 601 |
| Dedupe on email | 574 |
| Dedupe on email OR phone (union) | 533 |
| **Dedupe on normalised phone** | **560** |

**What the data shows:** there are two kinds of collision.

- **41 phone collisions are the same person.** The later record always has a mangled name
  (`SHREYA REDDY`, `pranav jain`, double spaces), a digit-suffixed email
  (`shreya.reddy92@outlook.com`), an id in the range C00561–C00601 and the *same time of day* on
  `created_at` as the original. That is a re-registration, not a different person.
- **24 email collisions are different people.** Identical common names
  (`divya.verma@protonmail.com` ×3), but every phone differs and nothing else links them. They
  are two people whose name produced the same address. Merging on email under-counts (533).

**What I did:** person identity = phone digits. The survivor is the earliest record.
`gold.dim_candidate` is at person grain. `gold.bridge_candidate_record` maps all 601 source ids
to their person, so nothing is lost.

**Open question for the client:** a strict reading of the global rule ("exclude records not tied
to a valid requisition") would drop the one person whose *only* application is an orphan
(C00263), giving **559**. It would also drop the 52 people with no application at all (507).
The control's 560 counts the whole pool, so the pool count is not filtered on applications.
Requisition scoping applies only when a hiring manager or recruiter is viewing.

## 2. At Offer on 31 March — 32

**The trap:** `applications.current_stage` is a denormalised "today" column. It disagrees with
the event history for 96 applications, and in any case it cannot answer a point-in-time
question.

| Rule | Result |
|---|---|
| `current_stage = 'Offer'` | 146 |
| Stage history, including orphan applications | 43 |
| **Stage history, valid requisitions only, at close of day** | **32** |

**What I did:** `gold.fact_stage_history` holds one row per period in a stage
(`valid_from`, `valid_to`). "At close of 31 March" means
`valid_from < 2026-04-01 00:00 AND (valid_to IS NULL OR valid_to >= 2026-04-01 00:00)`.

**Ordering:** 60 pairs of events share an identical `changed_at` (e.g. Interview → Rejected in
the same second). The order of truth is `event_seq`. In that order the `from_stage → to_stage`
chain is unbroken for all 1,450 applications. A sort on timestamp alone orders those 60 pairs
arbitrarily. Same-instant periods get `valid_from = valid_to`, so they are never "current" at
any cutoff.

## 3. Median time to hire — 58 days

| Rule | Result |
|---|---|
| Including orphan applications (104 hires) | 59 |
| Fractional days (`timestamp` difference / 86,400) | 58.54 |
| **Calendar days, applied date → Hired date, valid reqs (97 hires)** | **58** |

**What I did:** the Hired timestamp comes from stage history, not from `current_stage`.
24 applications still say `Offer` in `current_stage` but have a Hired event. 8 of the 104 hires
in the window sit on orphan requisitions, and including them moves the median to 59.
`applied_at` equals the first `Applied` event for every application (checked). Calendar-day
difference is the definition; it is stated in the metric's description.

## 4. Engineering offered salary — ₹200,700,000

| Rule | Result |
|---|---|
| Raw sum, Engineering | 20,070,000,000 |
| Corrected, but department taken from the offer sheet (includes 1 orphan offer) | 203,300,000 |
| **Corrected, department from the requisition, valid reqs** | **200,700,000** |

**The trap:** 111 of 421 salaries are exactly 100× a normal band (e.g. 260,000,000 against the
2,600,000 band). The genuine bands run ₹9 lakh–₹30 lakh, and every inflated value is one of
those bands × 100. This looks like a paise/rupee slip.

**What I did:** in Silver, any salary ≥ ₹1 crore is divided by 100. The raw value and
`salary_corrected = true` are kept for audit. Department is conformed from the requisition. The
offer sheet's own `department` column agrees for every valid offer, but it also tags orphan
offers, which is how 203.3M arises.

**Risk to flag:** a genuine ₹1 crore+ offer would be wrongly divided. The threshold is a
constant in `pipeline/silver.py`, and in production I'd confirm the unit with the source system
owner rather than infer it.

## 5. Offer acceptance rate — 51.25%

| Rule | Result |
|---|---|
| accepted / offers with a `decided_at` | 40.6% |
| Status-based, including orphans | 52.1% |
| **accepted / (accepted + declined), valid reqs** | **51.25%** |

**The trap:** all 91 open offers carry a `decided_at` date, so "has a decision date" counts open
offers as decided. Silver nulls `decided_at` on open offers and keeps the raw value as
`decided_at_raw`.

**The rounding difference:** 164 / 320 = 51.25 exactly, which sits on the rounding boundary.
The control's 51.2 is what round-half-to-even (Python's `round`) produces. Round-half-up gives
51.3. The metric returns **51.25** (two decimals), which is unambiguous and consistent with the
control. I did not change the data to make a one-decimal figure land.

**Also checked and not a cause:** 5 people received two offers on the same requisition. These
are separate applications on different dates (re-applications), so they are separate offers.
The fact grain is "one row per offer" and they are not deduplicated.

---

## Other data issues found (not in the controls)

| Issue | Count | Handling |
|---|---|---|
| Interviews pointing at application ids that don't exist (`A9xxxx`) | 9 | Kept, `application_missing = true`, `req_key = -1` |
| `current_stage` stale vs history | 96 | Derived from history in Gold; source column kept as `source_current_stage` |
| Interviews with no score | 180 | Left NULL (pending and no-show have no score) |
| Open offers whose application has since been Rejected/Withdrawn | 41 | Kept as `open` per the source. They are lapsed in practice; I'd raise this with the client, since it changes the acceptance denominator if they are treated as declined. |
| Names with stray whitespace or casing | 13+ | Collapsed and title-cased in Silver |
