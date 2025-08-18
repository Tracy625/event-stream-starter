# WORKFLOW — Mixed-Mode Kickoff

## Daily Routine

1. Update `/docs/STATUS.md`

   - Move yesterday's Today → Done·
   - Write new Today + Acceptance (2–3 items max)

2. In Claude Code, run `/clear`

3. Paste kickoff prompt (from /docs/KICKOFF.md)

4. Claude will:

   - Read BRIEF + STATUS
   - Confirm today's Acceptance
   - Decompose Today into Task Cards

5. You review Task Cards

   - Approve or adjust
   - Then say: "Approved. Proceed with Task [X]"

6. Claude implements Task [X]
   - Outputs plan (≤5 bullets), diffs, run/test commands
   - You run tests & commit

## Rules

- Only STATUS.md defines Today tasks
- Claude must never implement tasks not in STATUS.md
- Each Task = one cycle: Card → Approve → Execute → Test
