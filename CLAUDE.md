# SlowBooks Pro — AI Assistant Notes

Moshe is the product owner: a sharp non-coder working from an Android
tablet (GitHub web UI + chat only). **Before doing anything, read
`.claude/skills/working-with-moshe/SKILL.md`** — how to communicate with
him, how work is split between models, and how changes ship. Longer
version: `docs/WORKING-WITH-MOSHE.md`.

The short version:

- **Plan-first workflow**: the top-tier model (Fable/Opus class) plans and
  reviews by default — it never offers to implement, but Moshe's explicit
  ask clears it for anything, including merging PRs itself. Cheaper models
  (Sonnet/Haiku) implement from a finalized, self-contained plan and stop
  at opening the PR — they never merge, never push to main.
- All changes ship as PRs on `claude/*` branches. First line of every PR:
  **Risk: Low/Medium/High** + what could break + what to verify. Last
  line: **Test it** — exactly where to look/tap to see the change.
- Plain English, outcome first, warm and practical tone.

Project docs live in `docs/` (development.md, features.md, operations.md,
release-checklist.md and more) — consult them before changing code.
