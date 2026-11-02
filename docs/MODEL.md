# Gold dimensional model

```
                    dim_date
                       │
dim_user ──┬── dim_requisition ──┬── fact_application ──┬── fact_stage_history
           │   (req_key -1 =     │        │             ├── fact_offer
           │    Unknown)         │        │             └── fact_interview ── dim_user (interviewer)
           │                     │   dim_candidate (person)
           └─ hiring_manager_id / recruiter_id    │
                                       bridge_candidate_record (source record → person)
```

## Grain (one sentence each)

| Table | Grain |
|---|---|
| `fact_application` | One row per application: one source candidate record applying to one requisition at one moment. |
| `fact_stage_history` | One row per contiguous period an application spent in a single stage, from the event that entered it to the next event (`valid_to` NULL = still there). |
| `fact_offer` | One row per offer extended against an application. |
| `fact_interview` | One row per scheduled interview. |
| `dim_candidate` | One row per person (deduplicated on phone), not per candidate record. |
| `bridge_candidate_record` | One row per source candidate record, mapped to its person. |
| `dim_requisition` | One row per requisition, plus one `Unknown requisition` member (`req_key = -1`). |
| `dim_user` | One row per ATS user. |
| `dim_date` | One row per calendar day, 2025-09-01 to 2027-12-31. |

## Design decisions

- **Stage is history.** `fact_stage_history` is the only source for stage questions.
  `fact_application.current_stage` is derived from it (the period with `is_current`), and the
  untrusted source column survives only as `source_current_stage` / `source_stage_stale`.
  "At stage S at the close of day D":
  `valid_from < D+1 AND (valid_to IS NULL OR valid_to >= D+1)`.
- **Surrogate keys** are integers from `row_number()` over the natural key. Silver and Gold are
  full rebuilds, so keys are stable for unchanged data. For true incremental loads I'd persist
  a key-map table (natural key → surrogate key) so keys never move.
- **Orphans are kept, not dropped.** Facts that can't be tied to a requisition point to
  `req_key = -1` with `is_orphan = true`. Dropping them would hide a data problem from the
  people who need to fix it. Metrics exclude them, and only admins can see them.
- **Repeat candidates.** `fact_application.candidate_key` is the person, so "how many people"
  and "how many applications" are both one query. `source_candidate_id` keeps the record-level
  link.
- **Not SCD Type 2 yet.** The extract is a single snapshot, so there is no attribute history to
  track on requisitions or users. Bronze keeps every batch (`_batch_id`, `_loaded_at`), so the
  inputs for an SCD2 `dim_requisition` (for example a requisition moving between hiring
  managers, which changes access) accumulate from the second load onwards. See README,
  "Left out".
