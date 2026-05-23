# TODO / Working Notes

Internal scratchpad for things we know we need to do but haven't shipped
yet. Not user-facing — the README and CHANGELOG don't link here on
purpose. When something on this list lands, move it to `CHANGELOG.md`
under `[Unreleased]` and delete it from here.

---

## ⚠ Test coverage gaps — models without direct test imports

The audit found 20 models that aren't directly imported by any test
module. Most are exercised indirectly through their API routes (a
`POST /api/bills` test exercises `app/models/bills.py`), but no test
imports the model class and pokes its constraints / defaults / hybrid
properties directly. That's a real risk surface: subtle regressions
in constructors, computed columns, or relationship cascades can ship
silently.

**Priority — financial integrity (test these first):**
- `app/models/credit_memos.py` — reversing journal entries, balance math
- `app/models/recurring.py` — schedule generation, next-occurrence math
- `app/models/banking.py` — reconciliation state, bank-transaction matching
- `app/models/deductions.py` — pre/post-tax classification affects pay-run math
- `app/models/purchase_orders.py` — convert-to-bill workflow

**Priority — HR / payroll adjacent:**
- `app/models/hr.py` — onboarding tasks, employee documents
- `app/models/time_entries.py` — approval state machine, overtime math
- `app/models/tax.py` — tax-rate snapshots used by historical reports

**Lower priority — config / admin:**
- `app/models/settings.py`, `app/models/audit.py`, `app/models/backups.py`,
  `app/models/companies.py`, `app/models/email_log.py`,
  `app/models/email_templates.py`, `app/models/bank_rules.py`,
  `app/models/budgets.py`, `app/models/qbo_mapping.py`,
  `app/models/saved_reports.py`, `app/models/attachments.py`,
  `app/models/estimates.py`

Coverage strategy: a single `tests/models/test_<model>.py` per priority
item, asserting (a) construction with required fields, (b) defaults,
(c) computed columns / hybrid properties, (d) cascade deletes.

---

## Payroll / HR — still open

- **State unemployment filings (SUI)** — `app/services/tax_forms/state_sui.py`
  has scaffolding; needs per-state form rendering + an endpoint.
- **E-Verify submission flow** — schema already has
  `everify_case_number` but there's no submit / status-check integration.
- **Portal-token admin UI** — admin Employee Details modal should show
  "Last used N days ago" + "Expires DATE" alongside the token (the
  `expires_at` is already in the API response).
- **PTO accrual editor UI** — no SPA form for `POST /api/pto/accruals`.
  Admins currently use curl. Either build the form or add a "Enroll all
  active employees in policy X" button on the policies page.

---

## Security / ops — still open

- **CSP nonce migration** — drop `'unsafe-inline'` from `script-src`
  once index.html's 10 inline `onclick=` handlers and the hundreds of
  inline-event-handler templates in `app/static/js/*.js` are rewritten
  to `addEventListener` style. Real refactor (touches every JS file),
  not a quick fix.
- **Penetration test against a staging deploy** — external scope,
  can't be done in-repo.
- **`docker-compose.prod-nginx.yml` variant** — `docs/tls-proxy-setup.md`
  documents three TLS-proxy options (Caddy / nginx / Traefik). Bundling
  one into compose is an opinionated choice; current state is that
  ops picks their proxy and follows the doc. Acceptable as is unless
  feedback says otherwise.

---

## Frontend polish — still open

- **HSTS preload submission** — once the customer's TLS is locked in,
  optionally submit `books.example.com` to https://hstspreload.org/
  for browser pre-load. Manual step per customer.

---

## Polish

- **HSTS-preload helper doc** — short note in the release checklist
  about submitting the domain to the HSTS preload list (linked above).
- **README "What's New" trim** — every release, the top of the README
  drifts. Maybe move "What's New" into CHANGELOG entirely.

---

## Known small bugs

(none known as of this revision — pay-stub reimbursement display bug
fixed; portal token-in-URL leak closed by cookie-based session.)
