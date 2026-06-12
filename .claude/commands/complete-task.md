---
description: Complete a task — move plan file, update reference docs, review documentation. Run after code review is done.
---

# Complete Task

Final housekeeping after a plan has been implemented, tested, and code-reviewed. Does NOT commit — that's the user's job.

## Instructions

### 1. Identify the Plan File

Determine which plan was just completed:

- Check `$ARGUMENTS` first — if provided, find the matching plan in `docs/plans/`
- Otherwise, use conversation context — the plan file should have been referenced during implementation
- If ambiguous, ask the user

### 2. Move Plan to Completed

Move the plan file to `docs/plans/completed/` with **today's date** as prefix:

```
docs/plans/some-plan.md → docs/plans/completed/YYYY-MM-DD-some-plan.md
docs/plans/mtp/2026-03-07-mtp-1.7-quick-filter.md → docs/plans/completed/YYYY-MM-DD-mtp-1.7-quick-filter.md
```

Rules:
- Use plain `mv` — the user commits the move afterwards, git will detect the rename
- Strip the original date prefix if present — the completed date replaces it
- Keep the descriptive portion of the filename
- Strip subdirectory paths (e.g. `mtp/`, `perf/`, `annotations/`) — completed plans go flat into `completed/`

### 3. Clean Up Related Files

Delete associated files if they exist:

1. **Task file** — Check for a `.tasks.json` file alongside the plan (e.g., `docs/plans/mtp/some-plan.md.tasks.json`). If it exists, `rm` it.
2. **Spec file** — Check `docs/specs/` for a spec with a matching descriptive name (e.g., plan `mtp-1.7-quick-filter` matches spec `mtp-1.7-quick-filter-design.md`). Match on the descriptive portion, ignoring date prefixes. If found, `rm` it.

The user commits the deletions along with the move in section 2.

### 4. Update Reference Documents

Search for documents that link to the old plan path and update them:

1. **`docs/plans/mid-term-priorities.md`** — If this was an MTP item, update its status to "Done"
2. **Other plans** — Check `Depends on:` / `Blocks:` lines in related plans that reference this one; update paths
3. **Other docs** — Grep for the old filename across `docs/` and fix any broken links

### 5. Documentation Review

Check the plan file for an "Update Documentation" task. If it exists:
- Verify those documentation updates were actually done during implementation
- If any were missed, flag them to the user

If no documentation task exists, do a quick scan: does the implementation touch systems described in `docs/` or `packages/*/docs/`? Flag any docs that look potentially stale.

### 5a. In-File Documentation Review

List every new `.py` source file introduced by this plan under `src/cress/` (use `git status` / `git diff --name-only` vs. the previous commit; exclude `tests/`, `conftest.py`, and `__init__.py` re-export barrels). For each one, verify that it:

- Opens with a module-level docstring stating its responsibility and its place in the pipeline (per CLAUDE.md § Documentation Standards)
- Has a Google- or NumPy-style docstring on every public function describing inputs, outputs, and side effects
- Has full type annotations on every function, method, and public attribute (`mypy --strict` clean)

If any file is missing the module docstring, public-function docstrings, or type annotations, flag it to the user as a completion gap before the hand-off. Do not add the documentation silently here — surface the gap so the user can decide whether you should fill it in or they will.

### 6. Report and Hand Off

Report what was done:
- Which file was moved and where
- Which task/spec files were deleted (if any)
- Which reference documents were updated
- Any documentation gaps found

Then say: **"Ready for you to commit when you're happy."**

Do NOT commit, push, or create PRs.
