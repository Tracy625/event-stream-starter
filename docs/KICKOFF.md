# Day 1 Kickoff Prompt

Role: Senior engineer inside this repo. Follow CLAUDE.md strictly.

Task: Implement Day 1 tasks following the mixed-mode workflow.

Instructions:
1. Read /docs/BRIEF.md to understand product scope and users
2. Read /docs/STATUS.md to confirm today's Acceptance criteria
3. Decompose Today's tasks into Task Cards with this format:
   - Task: [Brief title]
   - Scope: [What to implement]
   - Acceptance: [How to verify]
   - Output: [Expected files/changes]

4. Present Task Cards and wait for approval before implementation

Task Card Template:
```
## Task Card [X]: [Title]
**Scope:** 
- [Specific implementation details]

**Acceptance:**
- [Verification steps]

**Output:**
- [Files to create/modify]
```

Rules:
- Do NOT implement before Task Cards are approved
- Each Task Card should be independently testable
- Follow the tech stack: FastAPI + Celery + Postgres + Redis
- Keep responses concise: plan → diffs → commands
- No auto-refactoring or bulk changes

Wait for: "Approved. Proceed with Task [X]" before implementation.