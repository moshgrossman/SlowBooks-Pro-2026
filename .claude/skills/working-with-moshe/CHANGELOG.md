# working-with-moshe — changelog

Old versions are kept whole in `archive/`. Every entry here ships in the
same commit as the version bump in SKILL.md.

## 2.2 — 2026-08-04
Moshe's third edit pass:
- Incubator is now a GitHub template repo; first-session cleanup steps
  for repos born from it recorded in the preamble.
- MDM exceptions: be mindful of time of day and request latency
  (phone = business hours, email = possibly next day); a design needing
  no exception at all is prioritized.
- Branch discipline sharpened into the four-states model: main = live,
  staging = testing (PRs in), one claude/* branch at a time = building
  (auto-deleted on merge; overlapping tasks are sequenced), plans =
  files in the repo, not a branch. AI proactively offers the
  staging-to-main promotion when done and tested.
- .txt files: small-screen writing spelled out (short paragraphs,
  blank line between every block).
- No-double-entry: "In short: friction is where users quit."

## 2.1 — 2026-08-04
Moshe's second edit pass, applied item by item:
- Skill itself is now versioned (this file + `archive/`).
- MDM exceptions: requested by email or a representative in business
  hours; used sparingly.
- Plans are ALWAYS offered as a downloadable .txt.
- Shipping: staging-first branch discipline — one source of truth for
  live/testing/planning, no competing branches (PodcastFeeder lesson);
  ask before anything goes to main.
- Planning: everything serious starts as a detailed plan expected to go
  back and forth; execute only at 100% same-page; push back on half-baked
  direction, especially late at night.
- .txt files: also attached in chat; written for his offline phone's
  notes app; spacing for a small screen.
- Product taste: "intuitive is the bar" added, generalized to any project
  (his philosophy); no-double-entry rationale in his wording;
  conversational-flow second example.
- Business context: reliability-for-users bullet in plain English.

## 2.0 — 2026-08-03
Full revamp in the incubator (`archive/` holds 1.x):
- Canonical-copy rule (incubator wins), durable-rules-only scope.
- Folded in the two sections that had drifted into PodcastFeeder only:
  .txt instructions workflow, versioning + self-update.
- New: content-filters section with MDM exception kinds and the Termux
  rule. Question-gets-an-answer emphasized; heimish-is-for-clients;
  DeX/Chrome-only environment; handoff offers at ~30% and ~50%; Test-it
  repeated in chat after deploy.

## 1.x — 2026-07 (archive/SKILL-v1-2026-07.md)
The version that lived in PodcastFeeder and property-manager, before the
incubator existed.
