# CLAUDE.md — Project Collaboration Rules

## Required Reading (every session)
- Read `/docs/BRIEF.md` to understand product scope and users.
- Read `/docs/STATUS.md` to know current progress, today's tasks, and acceptance criteria.
- Read `/docs/WORKFLOW.md` to follow the mixed-mode kickoff process
- Do not start coding before confirming understanding of both files.

## Guardrails
- Do **not** delete/rename/move files/dirs **unless I explicitly say**: "delete <file>" or "move <file> to <dir>".
- Show all changes as diffs. Never auto-apply or run bulk refactors.
- Keep responses concise: plan (≤5 bullets) → diffs → run/test notes.

## Tech & Repo
- Stack: FastAPI + Celery + Postgres + Redis; Next.js skeleton only.
- Modules: collector → filter(HF+rules) → mini-LLM refine → aggregator(event_key) → security scan(GoPlus) → DEX data → notifier(Telegram).
- Target P95: end-to-end ≤ 2 minutes.

## Workflow
1.Confirm today's acceptance criteria from `/docs/STATUS.md`.
2.Propose a plan (≤5 bullets). Ask for missing ONLY if blocking.
3.Produce diffs. Provide commands to run and minimal tests.
4.If external APIs rate limit, implement backoff + caching; document it.
5.Never perform “cleanup”, “auto-structure”, or “bulk rename”.

## When risky operations are requested
- Before deletion/moves, show a step-by-step plan and the exact diffs.
- Wait for my explicit phrase: "approved" to proceed.