# OrbitHR — Office Attendance & HR Management (test build)

A Qandle-inspired attendance + HR web app, fully functional end-to-end.

**Live demo:** https://orbithr-three.vercel.app
(also https://orbithr-llm-cc8e.vercel.app)

> **Hosting caveat:** Vercel functions have a read-only filesystem, so the live
> demo stores its SQLite DB in `/tmp` — storage there is **ephemeral** and the
> demo data re-seeds on cold starts. Treat the live site as a demo playground;
> for durable storage run `python3 app.py` on a persistent host (Railway,
> Render, Fly.io, a VPS) or port `db.py` to a hosted Postgres.

> **Stack note:** the original brief asked for Next.js / TypeScript / Tailwind /
> PostgreSQL. This machine has **no Node.js and no PostgreSQL** (only Python
> 3.13), so this test build uses the Python standard library (`http.server`) with
> **SQLite** for persistent storage and a hand-written Tailwind-style utility CSS.
> There are **zero external dependencies** — nothing to install. The schema in
> `db.py` is plain relational SQL and ports to PostgreSQL almost 1:1 (swap
> `INTEGER PRIMARY KEY` → `SERIAL`, `ON CONFLICT` works as-is). Routing, views
> and actions are organized so each view/action maps to a Next.js route handler
> if you later port it.

## Run

```bash
cd office-hrms
python3 app.py
# → http://127.0.0.1:8045
```

First run creates `hrms.db` and seeds realistic demo data: 15 employees across
5 departments, 3 shifts, 70 days of attendance history, leave requests in every
state, a missed clock-out, a pending comp-off, an onboarding employee and audit
history.

## Demo logins (password: `demo123`)

> These credentials are intentionally **not** shown on the login page — this
> README is the only place they are documented.

| Email | Role | Sees |
|---|---|---|
| `anika@acme.io` | **HR admin** | everything + employee admin, shifts, holidays, onboarding, QR kiosk, audit log |
| `rohan@acme.io` | **Manager** | own workspace + My Team, Approvals (direct reports only), Reports |
| `dev@acme.io` | **Employee** | own dashboard, attendance, leave, calendar, corrections, directory |

## Features (all functional, no mockups)

- **Attendance:** clock-in/out (office or WFH), live on-the-clock timer, breaks,
  automatic late-arrival minutes vs shift grace, overtime vs nominal shift
  hours, daily/monthly history, month navigation.
- **Leave:** apply (balance check, overlap check, weekly-offs/holidays excluded
  from day count), cancel, manager/HR approve–reject with comments, balances
  deducted and attendance marked on approval.
- **Employees:** searchable directory with department filter, rich profiles,
  departments, designations, reporting managers, HR add/edit with validation.
- **Role-based dashboards:** employee / manager / HR variants; server-side RBAC
  on every route and action (managers can only review their direct reports —
  verified by test).
- **Reports:** attendance-mix donut, daily headcount chart, department-wise
  absenteeism/hours/late/OT table, top late arrivals, downloadable daily and
  summary CSVs (scope-aware).
- **Shifts:** create shifts (hours, break, grace, weekly offs), assign
  employees, nominal-hours calculation feeds late/OT logic.
- **Notifications:** bell with unread count; alerts for missed clock-outs,
  pending approvals, leave/comp-off/correction decisions, shift changes,
  very-late arrivals.
- **Extras:** WFH mode tracking, QR kiosk with a real scannable QR
  (stdlib Reed–Solomon implementation in `qr.py`, daily-rotating token),
  attendance correction requests that rewrite records on approval, onboarding
  checklists with activation gate, comp-off credits for off-day work, and a
  full audit log.

## Security

- PBKDF2-HMAC-SHA256 passwords with per-user salts (60k iterations).
- Opaque session tokens, HttpOnly + SameSite cookies, 12 h server-side expiry.
- Per-session CSRF token required on every POST (verified by test).
- Role checks server-side on every GET route and POST action.
- All inputs re-validated server-side: dates, balances, overlaps, ownership,
  HTML-escaped output everywhere.

## Files

| File | Purpose |
|---|---|
| `app.py` | HTTP server, routing, sessions, RBAC, all POST actions, CSV export |
| `db.py` | Schema, seed data, business helpers (late/OT/working-day math) |
| `views.py` | GET page renderers (dashboard, attendance, leave, reports, admin…) |
| `ui.py` | Layout, utility CSS, components, SVG bar/donut charts, calendar |
| `qr.py` | Real QR-code generator (byte mode, ECC-L, v1–5) for the kiosk |
| `hrms.db` | SQLite database (created on first run; delete to re-seed) |

## Test results (run on this machine)

- 18/18 pages return 200 for HR; employee blocked (404) from all 9 manager/HR
  pages; manager blocked from HR-only pages.
- Clock-in → break → clock-out cycle computes late/OT; double clock-in rejected.
- Wrong CSRF token rejected; wrong password rejected; logout kills the session.
- Leave apply → manager approve: balance deducted, attendance marked,
  notification sent. Overlap and reversed-date applications rejected.
- Manager approving a non-report is denied (403-style redirect).
- Correction approval rewrote the attendance row (in/out/hours/late recomputed).
- QR check-in works with the valid daily token, rejects bogus tokens, token
  rotation invalidates old codes.
- Comp-off approval credited +1 Comp Off balance.
- Employee create/edit with duplicate-email rejection; onboarding activation
  gated on open tasks; holiday and shift CRUD work.
- CSV exports stream correctly (144 rows for the month).
- Data persists across server restart (648 attendance rows, 23 audit events).
