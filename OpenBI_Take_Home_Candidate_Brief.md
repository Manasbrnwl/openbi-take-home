# Take-home exercise — AI & Analytics Engineer

**OpenBI** · Role brief JD-2026-001

---

## Before you start

**Time cap: 16 hours, across a maximum of two days.** Stop at sixteen hours even if you are mid-flow. A well-judged partial submission beats a rushed complete one.

**This brief contains more work than fits in sixteen hours. That is deliberate.** Part of what we assess is what you build, what you drop, and whether you can say why. Do not attempt everything.

**Build it with a coding agent.** Whichever you drive — Claude Code, Codex, Cursor, Gemini CLI, Copilot, Cline, or anything else. This is required, not merely permitted, and how you drove it is scored directly. Commit the agent's context files and your plans alongside the code.

**You should not have to pay anything to sit this exercise.** If your usual agent is behind a subscription you do not hold, use a free one — the free tiers of Gemini CLI, GitHub Copilot and Cline are all sufficient for this, and we score how you direct the tool, not which brand it is. If cost is blocking you at any point, email us before you spend money.

**On the scenario:** Northbeam Partners is fictional and the data is synthetic. We are not building an ATS and we will not use your code. If you would rather solve the same problem in a different domain, tell us before you start and we will agree one.

---

## The situation

Northbeam Partners, a firm of around 400 people, has been running an applicant tracking system since September 2025. It works well enough for recruiters clicking through it one candidate at a time. It answers nothing at the aggregate.

Nobody can say how many people are in the pipeline, how long a hire takes, or whether one department's offers are being declined more than another's. The three attempts so far each produced a different set of numbers.

You are building the data layer that settles it, and a small application on top for the people who need to see it.

## The data

The data is in the `northbeam_ats_pack` folder alongside this brief. Seven files:

| File | Contents |
|---|---|
| `candidates.csv` | Candidate records |
| `applications.csv` | Applications. Note `current_stage`, a denormalised column the application maintains |
| `stage_events.csv` | Every stage transition recorded against an application |
| `requisitions.json` | Open and closed roles |
| `users.json` | Recruiters, hiring managers, admins |
| `interviews.json` | Scheduled interviews and outcomes |
| `offers.xlsx` | Offers extended, with salary and decision |

It is a raw production export and it has not been cleaned.

---

## Core deliverables

### 1. Pipeline and layers

Ingest all seven files into a Bronze, Silver, Gold structure. Local Parquet or DuckDB is fine — no cloud account needed here. Python, your stack.

- Bronze: as landed, with lineage and load timestamps.
- Silver: cleaned, typed, deduplicated, conformed.
- Gold: a dimensional model.

Re-running the pipeline must not duplicate data.

### 2. Dimensional model

A Gold star schema. We expect:

- A stated grain for every fact table, one sentence each.
- Surrogate keys.
- **A candidate's stage is a history, not a column.** "How many applications sat at Offer on 31 March" must be answerable, and it cannot be answered from a column that only knows about today.
- Deliberate handling of applications that cannot be tied to a requisition, and of candidates who appear more than once.

### 3. Reconciliation

`CONTROL_TOTALS.txt` in the pack holds five figures. Your Gold layer must reproduce all five:

1. Unique people in the candidate pool — **560**
2. Applications at Offer stage as at 2026-03-31 — **32**
3. Median time to hire, days — **58**
4. Total annual offered salary, Engineering, INR — **200,700,000**
5. Offer acceptance rate — **51.2%**

**Submit a reconciliation note** showing your figure against each control, and where you differed, what in the data caused it and what you did about it.

Read this section twice. Nothing in the data will throw an error to warn you, and every one of these figures has a plausible-looking wrong answer.

### 4. One metric layer

Define your metrics **once**, in code, in one place — time to hire, stage conversion, offer acceptance rate, and one period-over-period comparison.

The API reads those definitions. The frontend renders what the API returns. **No metric arithmetic in the frontend, and no second copy of a definition anywhere in the repository.** If time-to-hire changes definition, exactly one file should change.

This is the point of the exercise. Everything else is scaffolding.

### 5. The application

- A backend API over the Gold layer.
- A frontend that consumes it. Four or five numbers and a table is plenty — visual design is not scored.
- Authentication.
- **A hiring manager sees only their own requisitions and the candidates against them. A recruiter sees the requisitions they own.** Enforce it where it cannot be bypassed, and tell us in the README how you satisfied yourself that it cannot be. Assume this data is real personal information, because in production it would be.

CRUD screens are assumed and carry no marks. Build the thinnest thing that demonstrates the above.

### 6. Deployment

Deploy it somewhere and give us a working URL, plus a note on what you would change before real users touched it.

**Use whatever host is free for you.** Render, Railway, Fly, Vercel, Netlify, Cloudflare, Azure, Oracle — any of them is fine and none scores higher than another. We are assessing whether you can get an application running outside your laptop and reason about it, not which vendor you picked.

If you use AWS, stay inside the always-free services — Lambda, DynamoDB, S3, CloudFront. Those allowances reset monthly and never expire, whatever the age of your account. Do **not** stand up EC2 or RDS for this: AWS changed its free tier in July 2025, and on an account opened before that date those services will bill you.

**Do not spend money on this exercise.** If deployment would cost you anything, run it locally, say so in the README, and describe how you would deploy it. That answer is worth nearly full marks. A candidate who reasons clearly about deployment costs and declines to pay has demonstrated something we actively want.

### 7. Agent worklog and artifacts

Commit:

- Your agent context file — `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, whatever your tool uses.
- The plans or specs you handed the agent, as you wrote them.
- Commit history granular enough to show how the build actually went. One squashed commit tells us nothing.

Plus one page covering: what you delegated that worked; what you deliberately did **not** delegate, and why; and one thing the agent got wrong that you caught — how you caught it, and what you changed in how you prompted afterwards.

A generic worklog scores zero. We go through it line by line.

### 8. Estimate versus actual

Estimate hours per section before you start. Record actuals. Submit both, with two lines on where you were most wrong.

---

## Extensions

Only if the core is genuinely finished. **Pick one.**

**A · Ask it anything.** An MCP server or agent answering plain-language questions against your Gold layer, reusing the metric layer rather than writing fresh SQL per question. Include how you would evaluate whether its answers are correct — that matters more than the feature.

**B · Performance.** Your heaviest transformation and your heaviest endpoint, each made materially faster. Before-and-after timings, what you changed, how you measured. Numbers, not adjectives.

**C · Security review.** Review your own submission as a client's auditor would. Findings with severity, fixes, evidence each fix works. Three real findings beat ten generic ones.

---

## What we are actually assessing

- Whether your five numbers tie, and whether you noticed when they did not.
- Whether stage history is modelled as history.
- Whether a metric is defined once or quietly three times.
- Whether access control holds when someone edits the request.
- Whether you direct the agent or follow it.
- Whether a colleague could clone the repository and be productive in ten minutes.

## What we are not assessing

- Visual design.
- CRUD completeness.
- Volume of code. Less is usually better.
- Whether you finished an extension.

---

## Submitting

A Git repository — public, or private with access shared — containing the pipeline, the metric layer, the application, the agent artifacts, the reconciliation note, the worklog, the estimate table, the deployed URL, and a README covering how to run it and what you left out.

Send the link to **harry@openbi.ai** within four calendar days of receiving this brief.

The follow-up is a sixty-minute conversation. We will open your code, question the design, change a requirement and ask how you would absorb it, and work through the agent worklog. Come ready to defend your choices and to say plainly which ones you would now make differently.
