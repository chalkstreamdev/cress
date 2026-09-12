---
description: Brainstorm a design and write it up as a spec — e.g. /brainstorm cloud sync for the library
---

# Brainstorm

You explore a problem with the user through conversation, then write the outcome up as a spec in
`docs/specs/YYYY-MM-DD-description-of-task.md`. The spec is the *what and why* — problem,
decisions, and the alternatives they beat. The *how* comes later, from `/plan`.

**Never use the `AskUserQuestion` tool anywhere in this command** — it is unreliable in this
terminal and truncates option text. Ask in plain text at the end of a turn, then end the turn. No
spacing tricks or padding.

**Never commit.**

## Instructions

### 1. Understand the problem before proposing anything

Read first, ask second:

- `docs/` for how the affected systems are described today
- `docs/specs/` and `docs/plans/` (including `completed/`) for prior thinking on this — an idea that was already rejected, and why, is the most useful thing you can find. Both folders are new and may be empty; `docs/plugins.md` and `README.md` carry the design history that predates them
- The actual code at the boundary being discussed

Then state your understanding of the problem in a few sentences and check it. Getting the problem
wrong is the failure mode that wastes the whole conversation.

### 2. Explore, one question at a time

This is a dialogue, not a questionnaire. **Ask one question per turn, then end the turn and wait.**
A wall of ten questions gets a wall of ten shallow answers.

Good questions in rough order:

- **Problem** — who hits this, how often, what do they do instead today? What happens if nothing is built?
- **Boundaries** — what is explicitly not in scope? What must not change?
- **Constraints** — what does this have to live with? Existing data, existing users, a one-person maintenance budget, a deployment shape.
- **Shape** — the two or three genuinely different ways this could work, with the trade-off named for each. Offer a recommendation; don't hide behind neutrality.
- **Failure** — what does this look like when it goes wrong, and what's the recovery?

Push back when an answer doesn't hold up. Agreeing with everything produces a spec that documents
enthusiasm rather than a design. Where the user's answer settles something, say so and move on —
don't re-open it later in the conversation.

**Keep a running list of decisions and rejected alternatives as you go.** The rejected ones are
half the value of the document; if you only capture them at the end, you'll have lost the reasons.

### 3. Know when to stop

Stop exploring and offer to write it up when the problem, the boundaries, and the shape are settled
— even if details remain. Unresolved details belong in the spec's **Open questions** section, not
in an endless conversation.

Ask, in plain text: whether to write the spec now, keep exploring a specific area, or leave it
as conversation. Then end the turn.

### 4. Write the spec

Follow `spec-template.md` in `chalkstream.dev/docs/templates/planning/`. Non-negotiables:

- **Filename:** `docs/specs/YYYY-MM-DD-description-of-task.md`, today's date, lowercase kebab-case.
- **Header list:** a bulleted list, one bullet per field: `**Date:**`, `**Status:**`, `**Type:** Spec (what & why)`, `**Plans:**`, `**Scope:**`, `**Depends on:**`, `**Blocks:**`, `**Related:**`. A field with more than one entry puts each entry on its own nested bullet — never joined with " · " on one line, and never as bare lines, which Markdown renders as one paragraph. `Status` takes one of the six vocabulary phrases from `planning-standards.md` § 2.1 — `Exploring` or `Direction accepted` for a new spec. `Plans` starts as `None yet`; it is the only place the spec points at its own plans, so `Type` and `Blocks` carry no plan pointer.
- **Edit Summary table** immediately after the header block.
- **Named decisions, numbered for linking** — the heading reads **Decision 1 — <short name>**, so a link has a stable target. In prose, refer to a decision by its name, never as a bare label such as "D1". Each states what was chosen, what it beat, and why in a sentence.
- **A Rejected alternatives section** with the reason for each. This is the section that stops the same idea being re-litigated in six months.
- **Open questions** and **Non-goals** sections, both real. "None" is an acceptable answer; an absent section isn't.

Write what was decided, not a transcript of how. If something was measured or tested during the
conversation, record the numbers and the date — a spec grounded in a measurement outranks one
grounded in a guess.

Designs in this repo must account for: the **pure core, thin shell** rule (parsers, resolvers and
generators are pure functions returning in-memory `OutputFile`s; the manifest writer is the only
thing that touches disk); **no CSS pipeline inside cress** (it consumes the consumer's build
manifest, it never compiles or transforms stylesheets); **boundary-only validation** with no
defensive fallback chains; **`build` is lenient, `validate` is strict**; and the fact that cress is
a public, reusable tool — a design that only works for one consumer's vault layout is the wrong
design.

Finally, rebuild the specs index so it picks up the new spec. From the repo root:

```bash
python3 /mnt/x/SynologyDrive/Development/chalkstream/chalkstream.dev/scripts/build_specs_index.py
```

The script writes `docs/specs/README.md`; never edit that file by hand.

### 5. Report

Say where the spec was written and summarise the decisions in a few lines. Then offer the next
step: `/critique <name>` to review it, or `/plan <name>` to turn it into an implementation plan.

## Important

- One question per turn. This is the rule that makes the command worth having.
- Explore genuinely — if the honest answer is "this isn't worth building" or "the existing thing already does this", say so. A brainstorm that talks the user out of work is a success.
- Don't write the spec early. A spec written before the direction settles becomes a document nobody trusts.
- Don't design what wasn't asked about. Adjacent ideas go in Open questions or Non-goals.
- Never use `AskUserQuestion` — ask everything in plain text and wait for the reply.
