# Worklog

I built this with Claude Code, running two sessions at once. Session A did the data work: loading
the files, cleaning, the Gold model, the metrics and the reconciliation. It also handed work to
session B and checked what came back. Session B built the API, login, access rules and the web
page, and later did the security review. The detailed notes each session kept as it went are in
`worklog-notes-session-a.md` and `worklog-notes-session-b.md`. This page is the short version.

## How I started

My first instruction was not to write any code. I asked for a list of every piece of work, which
data file feeds which part, and where each one gets used. That list came back with a first look
at the data. It showed 601 candidate records but only 574 emails, applications pointing at
requisitions that don't exist, and some salaries 100 times too big. I read it, agreed the order
and the hour estimates, and only then said go. That list is `docs/plans/01-initial-plan.md`.

## What I handed over and it worked

- **The data digging.** Working out why each control total has a believable wrong answer took a
  lot of small queries. The agent ran them, and the reconciliation note shows the wrong number
  each trap gives next to the right one. That table makes it easy to check the reasoning instead
  of taking it on trust.
- **Splitting work between two sessions using a written contract.** Session B never touched the
  data code. It built against `docs/CONTRACT.md` and a shared `Scope` type, and the two sides
  joined up first time.
- **Attacking the access rules.** Session B tried forged tokens, swapped user ids and added
  `?role=admin`. Then it broke the app on purpose four ways to prove the tests catch each break.
  That's stronger evidence than tests that only ever pass.

## What I didn't hand over

- **Publishing and money.** Whether the repo is public, which host to use, signing in to Render,
  and the live password were my decisions, and I did those steps myself. I chose a free host
  because the brief said not to spend anything, and I wasn't going to find out about a bill after
  the fact.
- **The password.** It's in the Render dashboard and in my email to you, not in the repo.
- **Saying something is finished.** I didn't accept "it works" from either session. I asked for
  the test run and for checks against the live site. The deployed app was checked after I put it
  up: all five figures, plus a hiring manager trying to see another manager's requisition.

To be honest about it: the data choices, like matching people on phone number rather than email,
were made by the agent, not by me. I made sure each one was backed by numbers and written down so
I could check it and defend it. Next time I'd look at those choices myself before the pipeline
was built on them, not after.

## The mistake I caught

I set up a second session so the work could run in parallel. The first session kept doing
everything itself, one step after another, and the second one sat idle. I noticed and asked why
it wasn't using the other session.

The honest answer was that it wanted the data model settled first so the other session had
something stable to build on. That's a fair reason, but it should have said so up front instead of
quietly going serial. After I asked, it wrote down the table layouts and the metric functions as a
contract, committed the shared access-scope code, and handed session B a full plan. From then on
both sessions worked at the same time. The API, login and access tests were done while the
reconciliation was still being written.

What I changed in how I prompt: when I give an agent extra help, I now tell it what each helper is
for and ask it to show me the split before it starts. I also ask it to say when it is waiting on
something, rather than just carrying on alone.

The agents also caught several of their own mistakes. The worst was a join that silently dropped
9 interviews. Another was a git setting that would have changed the line endings in the raw data
files. Both are written up in the session notes, along with how each was caught.
