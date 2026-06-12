---
description: Critique an implementation plan — e.g. /critique mtp-1.7-quick-filter
---

# Plan Critique

You deeply review an implementation plan, identifying strengths and potential issues, then guide the user through resolving each issue interactively.

## Instructions

### 1. Find the Plan

Parse `$ARGUMENTS` to locate the plan file:

- If it looks like a path (contains `/` or `.md`), read it directly
- If it looks like a partial name (e.g. `quick-filter`, `mtp-1.7`, `chart-theme`), search `docs/plans/` recursively for a matching file
- If multiple matches, list them and ask the user to pick one
- If no argument provided, list recent plans in `docs/plans/` (excluding `completed/`) and ask which to critique

### 2. Read and Understand the Plan

Read the full plan file. Also:

- Read any files the plan references modifying (skim the key ones to understand current state)
- Check `docs/plans/` for related plans mentioned in `Depends on:` / `Blocks:` lines
- Read relevant docs in `docs/` if the plan touches documented systems
- **Read the Edit History section** (if one exists). Prior critique sessions record what was already fixed and what was deliberately skipped with reasoning. Factor this into your review — don't re-raise issues that were already addressed, and don't re-raise skipped issues unless you have a materially different argument than the one already considered

### 3. Deep Review

Think deeply about the plan. Evaluate it across these dimensions:

**Correctness**
- Will the proposed approach actually work?
- Are there edge cases the plan misses?
- Are the architectural decisions sound?

**Completeness**
- Are all necessary files identified?
- Are there missing tasks or steps?
- Does it handle error cases appropriately?
- Is the testing strategy sufficient?

**Consistency**
- Does the approach match existing project patterns? (Check CLAUDE.md for conventions)
- Are there conflicts with other planned or completed work?
- Do the dependency declarations (`Depends on:` / `Blocks:`) look correct?

**Risk**
- Are there tasks that could have unintended side effects?
- Is there a risk of data loss or breaking changes?
- Are there performance implications not addressed?

**Sequencing**
- Is the task order logical?
- Could any tasks be reordered for better incremental progress?
- Are there tasks that should be split or merged?

**Reuse**
- Does the plan reuse existing modules, helpers, and utilities from `src/cress/`?
- Check the module layout in CLAUDE.md — `slugify`, `post`, `render`, `wikilinks`, `attachments`, `taxonomy`, `pages`, `feeds`, `shortcodes`, `plugins`, `manifest`, `config` — for overlapping functionality before introducing new code
- Prefer extending existing pure functions and dataclasses over adding parallel ones
- If the plan explicitly chose NOT to reuse something, check whether the justification is sound
- Common reusable pieces: `SiteConfig`, `Post`, `SlugPlan`, `OutputFile`, the `plugin` registry, the mistune renderer, the Django template engine wrapper, the manifest writer
- Prefer stdlib and already-declared dependencies (`mistune`, `python-frontmatter`, `django`, `PyYAML`, `Pygments`, `feedgen`, `GitPython`, `watchdog`, `typer`) over pulling in new ones

**Typing and Documentation**
- Does every new function, method, and public attribute have a full type annotation? The project enforces `mypy --strict`
- Does every new module in the plan's code samples open with a module-level docstring that states its responsibility and its place in the pipeline?
- Does every new public function have a Google- or NumPy-style docstring describing inputs, outputs, and side effects?
- Flag any `Any` usage that isn't accompanied by a `# type: ignore` + justification
- Check that immutable value types use `@dataclass(frozen=True, slots=True)`

**Simplicity**
- Is the plan over-engineered for what it needs to do?
- Are there simpler approaches that would achieve the same goal?
- Does it introduce unnecessary abstractions?

### 4. Present the Review

Structure your response as:

#### What's Good

Highlight the strengths of the plan — good architectural decisions, thorough testing, clean task breakdown, etc. Be specific, not generic praise.

#### Issues Found

If there are issues, present a numbered summary list. Each item should be one line with a severity tag:

- `[major]` — Could cause the implementation to fail or produce wrong results
- `[moderate]` — Worth changing but not a blocker
- `[minor]` — Polish, style, or small improvement

Example:
```
1. [major] SQL injection risk in quick filter — user input not escaped before interpolation
2. [moderate] Task 3 modifies TableEditor but doesn't account for the existing filter merge logic
3. [minor] Test in Task 2 doesn't cover unicode characters in search text
```

If no issues are found, say so clearly: "No issues found — this plan looks solid and ready to execute." Then log a clean-pass entry in the Edit History and Edit Summary table (see section 6) and skip the interactive resolution steps:

```markdown
### 2026-03-24 — Critique

No issues found.
```

Add a row to the Edit Summary table: `| 2026-03-24 | No issues found | Clean pass |`

Then use the `AskUserQuestion` tool to ask whether to step through issues (only when there are issues):

```
AskUserQuestion({
  questions: [{
    question: "Shall we step through each issue with alternatives and recommendations?",
    header: "Review",
    multiSelect: false,
    options: [
      { label: "Step through issues", description: "Walk through each issue one at a time with fix options" },
      { label: "Apply all recommended", description: "Auto-apply the recommended fix for every issue" },
      { label: "Just show the summary", description: "I'll read the review and handle fixes myself" }
    ]
  }]
})
```

### 5. Interactive Issue Resolution

If the user chose "Step through issues", work through each issue sequentially:

For each issue:

1. **Explain the issue** in detail — what's wrong, why it matters, what could go wrong
2. **Present choices using `AskUserQuestion`** — always include the recommended fix first with `(Recommended)` in its label, plus a "Dismiss" and "Discuss more" option:
3. **Make sure there are two line breaks (`\n\n`) at the start of the question** in `AskUserQuestion` — this prevents the last line of the explanation from being truncated in the UI.

Then ALWAYS write four carriage returns before asking the user. This must come before the horizontal rule that appears with AskUserQuestion.
```
AskUserQuestion({
  questions: [{
    question: "How should we resolve: [brief issue description]?",
    header: "Issue N",
    multiSelect: false,
    options: [
      { label: "[Fix approach] (Recommended)", description: "[why this is the best option]" },
      { label: "[Alternative approach]", description: "[trade-off]" },
      { label: "Dismiss", description: "Not a real issue, move on" },
      { label: "Discuss more", description: "I want to explore this further before deciding" }
    ]
  }]
})
```

3. **Wait for the user's choice** — do not proceed until they respond

If the user picks "Discuss more", explore the topic conversationally, then re-present the choices with `AskUserQuestion` again (updated if the discussion revealed new options).

After the user decides:
- Note down the resolution
- Move to the next issue: "Moving on to issue N..."

Track resolutions as you go. Do NOT edit the plan until all issues have been resolved.

### 6. Apply Changes to the Plan

After all issues are resolved, edit the plan file to incorporate the approved changes. For each accepted change:

- Modify the relevant task descriptions, code examples, file lists, or architecture notes
- Keep the plan's existing structure and style
- Don't rewrite sections that weren't affected by the critique

#### Edit Summary Table

After making changes, add or update an **Edit Summary** table near the top of the plan — immediately after the header block (Goal, Architecture, Tech Stack, Depends on/Blocks, etc.) and before the first task or section divider (`---`). If the table already exists, append a new row. If it doesn't exist, create it.

Format:

```markdown
## Edit Summary

| Date | Changes | Summary |
|------|---------|---------|
| 2026-03-24 | 3 fixes, 1 skip | Parameterized SQL queries, unicode test coverage, filter merge order kept |
```

- **Date**: `YYYY-MM-DD` of this critique session
- **Changes**: Count of fixes and skips (e.g. "2 fixes, 1 skip" or "No issues found")
- **Summary**: One-line description of what changed — focus on the substance, not the severity tags

#### Edit History Log

After making all other changes, add or update an **Edit History** section at the very bottom of the plan file. If the section already exists, append a new subheading for today's critique. If it doesn't exist, create it.

Format:

```markdown
## Edit History

### 2026-03-24 — Critique

**Fixes:**
- **[major] SQL injection in quick filter** — User input was interpolated directly into the SQL string. Changed to use parameterized queries via DuckDB's prepared statement API.
- **[moderate] Missing test for unicode search** — Quick filter tests only covered ASCII. Added a test case with CJK and emoji characters to verify the ILIKE clause handles multi-byte input.

**Skips:**
- **[moderate] TableEditor filter merge order** — Dismissed because the current merge order matches AG Grid's documented precedence and changing it could break column-level filters.
```

Each critique session gets its own subheading dated `YYYY-MM-DD`. Under it:
- A **Fixes** bullet list — one bullet per accepted fix, tagged with severity. Each bullet has the issue title in bold, then a sentence or two describing the problem and how the plan was changed to address it.
- A **Skips** bullet list — one bullet per dismissed issue, tagged with severity. Each bullet has the issue title in bold, then a sentence or two describing the problem and why it was decided to skip the change.
- Omit either section if there are no fixes or no skips for that session.

#### Changes Summary

After editing, show a brief summary of what was changed:

```
## Changes Applied
- Issue 1: [what was changed]
- Issue 3: [what was changed]
- Issue 2: dismissed — no change
```

## Important

- Be genuinely critical — the point is to catch problems before implementation, not to rubber-stamp
- But don't invent problems — if the plan is good, say so
- Ground your critique in the actual codebase, not hypotheticals. Read the files being modified.
- Respect the project's conventions: TDD-first, `uv` for all Python commands, `mypy --strict`, `ruff` clean, frozen dataclasses, pure core + thin shell, boundary-only validation
- Flag any plan that writes implementation before tests, or skips the "verify test fails" step — that violates the TDD rule in CLAUDE.md
- Flag any plan that proposes `git add` / `git commit` / branches / worktrees — CLAUDE.md forbids them
- Don't suggest changes that conflict with CLAUDE.md guidelines
- Keep the interactive flow conversational — don't dump walls of text
- If an issue is dismissed, respect that and move on
