---
description: Complete a task — move plan file, update reference docs, review documentation. Run after the work is reviewed.
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
docs/plans/sub-folder/2026-03-07-quick-filter.md → docs/plans/completed/YYYY-MM-DD-quick-filter.md
```

Rules:
- Use plain `mv` (create `docs/plans/completed/` first if it doesn't exist). Not `git mv` — that stages the change, and staging is the user's job; git detects the rename at commit time either way
- Strip the original date prefix if present — the completed date replaces it
- Keep the descriptive portion of the filename
- Strip subdirectory paths — completed plans go flat into `completed/`

### 3. Clean Up Related Files

1. **Task file** — Check for a `.tasks.json` file alongside the plan (e.g. `docs/plans/some-plan.md.tasks.json`). If it exists, `rm` it. The user commits the deletion along with the move in section 2.
2. **Spec file** — Find the spec this plan implements and record the completion in its header. **The spec stays where it is — specs always stay.** A spec is standing reference for the *what and why* and outlives its plan; completion never deletes, moves, or re-dates it, and there is nothing to ask the user. Lookup order:
   1. Grep `docs/specs/` for a `Plans` bullet that links this plan (by its old path) — the reliable inverse link.
   2. Otherwise, the name match: a spec whose descriptive filename matches the plan's (e.g. plan `quick-filter` matches spec `quick-filter-design.md`), ignoring date prefixes. This covers plans written before the `Plans` field existed.
   Do not use a `../specs/` link in the plan's own header: a plan's `Related` field often links several specs.

   When the spec is found, update its header (the rules are in `planning-standards.md` § 2.1):
   - Change the plan's `Plans` bullet to end ` — complete YYYY-MM-DD` (today, the date in the new filename) and rewrite its link to the `completed/` path. Add the bullet if the spec has no `Plans` field yet, moving any plan pointer out of `Type` or `Blocks` at the same time.
   - Set `**Status:**` to `Implemented` when every `Plans` bullet is `complete` (ignoring `rejected`), and to `Partly implemented` otherwise. Keep any useful free text after ` — `.
   - Bump the spec's `**Date:**` and add an Edit Summary row: `| YYYY-MM-DD | Plan complete | <plan filename> completed |`.

   If the shipped work contradicts the spec, flag that in the Documentation Review (section 5) instead of editing the body.

   **Cross-repo case:** when nothing here matches, grep the sibling repos' `docs/specs/` folders under `/mnt/x/SynologyDrive/Development/chalkstream/` for a `Plans` bullet that links this plan by its cross-repo path. If one is found, do not edit the other repo — flag it to the user with the exact bullet to change (cross-repo stale links are flagged, not fixed). That repo's `docs/specs/README.md` shows the plan as `active` until the user updates it.

### 4. Update Reference Documents

Search for documents that link to the old plan path and update them:

1. **Other plans** — Check `Depends on:` / `Blocks:` lines in related plans that reference this one; update paths
2. **Other docs** — Grep for the old filename across `docs/` and fix any broken links
3. **Cross-repo links** — If the plan is referenced from sibling repos (grep the `docs/` folders of the other projects under `/mnt/x/SynologyDrive/Development/chalkstream/`), flag those stale links to the user rather than silently editing another repo
4. **Specs index** — Rebuild `docs/specs/README.md` from the repo root: `python3 /mnt/x/SynologyDrive/Development/chalkstream/chalkstream.dev/scripts/build_specs_index.py`. Never edit that file by hand

### 5. Documentation Review

Check the plan file for an "Update Documentation" task. If it exists:
- Verify those documentation updates were actually done during implementation
- If any were missed, flag them to the user

If no documentation task exists, do a quick scan: does the implementation touch systems described in `docs/`? Flag any docs that look potentially stale.

### 5a. In-File Documentation Review

List every new `.py` source file introduced by this plan under `src/cress/` (use `git status` / `git diff --name-only` vs. the previous commit; exclude `tests/`, `conftest.py`, and `__init__.py` re-export barrels). For each one, verify that it:

- Opens with a module-level docstring stating its responsibility and its place in the pipeline (per CLAUDE.md § Documentation Standards)
- Has a Google- or NumPy-style docstring on every public function describing inputs, outputs, and side effects
- Has full type annotations on every function, method, and public attribute (`mypy --strict` clean)

If any file is missing the module docstring, public-function docstrings, or type annotations, flag it to the user as a completion gap before the hand-off. Do not add the documentation silently here — surface the gap so the user can decide whether you should fill it in or they will.

### 6. Completion Log

Before the hand-off, record the outcome in the plan itself (in its new `completed/` location):

- Append a subheading to the plan's **Edit History** section — create the section at the bottom of the file if it doesn't exist. Use today's date with the label "Plan complete", followed by a bullet list of any deviations or edits made during implementation (e.g. "Task 4 split into two steps; skipped the proposed helper in Task 6 — inline approach simpler"). If implementation followed the plan exactly, write a single bullet: "No deviations."
- Add a row to the **Edit Summary** table near the top (create it if it doesn't exist — same location `/critique` uses: after the header block, before the first task or divider): `| YYYY-MM-DD | Plan complete | One-line summary of deviations or "No deviations" |`

### 7. Report and Hand Off

Report what was done:
- Which file was moved and where
- Whether a task file was deleted (companion specs always stay put)
- Which reference documents were updated
- Which spec was updated and its new `Status`, or which cross-repo spec bullet needs a hand edit
- Any documentation gaps or stale cross-repo links found

Then say: **"Ready for you to commit when you're happy."**

Do NOT commit, push, or create PRs.
