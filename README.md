# Nowshera Events Co.

A responsive event platform with a **Python FastAPI backend**, **Supabase Auth**, and **Supabase Postgres**. No offline database and no pretend bookings.

## What is ready

- `/events`: published future events, search, category filters, event detail dialog and availability.
- Account creation, email/password login, token refresh and logout.
- `/registrations`: private booking history and eligible cancellation.
- `/admin`: backend-authorized dashboard, create/edit/publish/cancel/complete/delete, attendee search/status filter and CSV export.
- Responsive navy/white/gold UI, keyboard controls, accessible native dialogs and reduced-motion support.
- Supabase schema installed in the connected `database+table` project. Existing unrelated tables were not modified. Event tables start empty; no invented client events were published.

## Run on your computer

Install Python 3.12 or newer. Open a terminal in this folder:

```sh
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

macOS/Linux:

```sh
source .venv/bin/activate
```

Then:

```sh
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000/events and http://localhost:8000/admin.
The Python server serves both the UI and API, so no frontend build is needed.
The connected project's URL and public publishable key are preconfigured. They are not service secrets. Environment variables can override them. `.env.example` documents the variables; set them in your shell or hosting dashboard (the app does not automatically load .env files).

## First administrator

1. Open the application and create an account using your real email.
2. Confirm your email from Supabase, then sign in.
3. In the Supabase SQL editor, run the statement below with the exact email. Do not grant a role to an unknown account.

```sql
insert into public.nec_admins(user_id)
select id from auth.users where lower(email)=lower('YOUR_ADMIN_EMAIL')
on conflict do nothing;
```

4. Open `/admin`. Create a draft event, complete its details, select **published**, and save.

An attendee cannot promote themselves. Admin membership lives in a private-access table, not editable user metadata. No default admin password or privileged test account is included.

## Deploy the complete Python application

The recommended deployment is the included Dockerfile on a Python/Docker host. It serves both frontend and backend from one HTTPS origin.

```sh
docker build -t nowshera-events .
docker run --rm -p 8000:8000 nowshera-events
```

Set `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` in the host's environment. Set the Supabase Authentication Site URL to the actual HTTPS app URL and configure allowed redirect URLs. Email confirmation must remain enabled as appropriate for your project. Configure production SMTP and auth rate limits in Supabase for a real public launch.

The saved Sites version is a **frontend preview**, not a running Python deployment. It can read public upcoming events from Supabase, and shows an explicit preview notice; account, booking and administration requests require the Python server. To use a separate deployed frontend, set `API_BASE` in `dist/assets/config.js` to your Python API HTTPS origin and set `ALLOWED_ORIGINS` on Python to that exact frontend origin. Re-publish the frontend after changing this value. No hosting account or Python deployment URL was provided, so full live deployment remains pending.

## Security and business rules

Browser → Python `/api` → Supabase Auth verification → Supabase RPC → Postgres.

Python validates event input, verifies access tokens using Supabase's user endpoint, and checks administrator membership. It forwards the user's token, never a service-role key.

All three event-system tables have RLS enabled and direct `anon`/`authenticated` table access revoked. The public SQL wrapper is SECURITY INVOKER. Its implementation is in the unexposed `nec_private` schema with a fixed empty search path, explicit identity/ownership/administrator checks and restricted execution privileges. It uses elevated rights specifically to perform authorized cross-table operations and count all bookings without revealing private attendee records.

Registration, cancellation and event changes take the same event-row lock. Active capacity is counted under that lock. A partial unique index is an additional duplicate guard. Cancelling releases a seat. Past, draft, cancelled and completed events reject new bookings. Capacity cannot fall below active bookings. Closed events cannot reopen; published events cannot return to draft. An event may be marked completed after its start time. Deletion is allowed only without registration history; otherwise cancel it to preserve records. Cancellation closes at the start time or when the event is cancelled/completed. Existing bookings on cancelled events remain historical records and show the event's cancelled state.

All stored timestamps use timestamptz. The interface consistently shows Pakistan Standard Time; the event editor explicitly interprets local input as UTC+5.

CSV export includes all event registrations with status, uses UTF-8 BOM for Excel, and neutralizes formula-leading cells. Tokens are kept in sessionStorage (persist across refresh, cleared when the tab session ends), with refresh support. Serve over HTTPS; do not add untrusted third-party scripts.

### Existing project findings

The connected Supabase project already has `public.users` and `public.posts` with RLS disabled. These are unrelated to this application and were not changed. Review their existing consumers before enabling RLS and adding appropriate policies. Optional remediation starting point (not applied):

```sql
alter table public.users enable row level security;
alter table public.posts enable row level security;
```

This blocks API access until suitable policies are added. See https://supabase.com/docs/guides/database/postgres/row-level-security.

The event tables intentionally have RLS enabled with no table policies because direct table access is denied and the authorized private function owns all access. The advisor's informational `rls_enabled_no_policy` notice is expected for this architecture.

## Tests and evidence

```sh
python -m unittest backend.test_api -v
```

A live read through Python to Supabase returned HTTP 200. Four API tests passed: unauthenticated access/input validation/page routes, non-admin rejection, user-token forwarding, and CSV formula safety.

`database/acceptance_tests.sql` ran against the connected Supabase database: **14/14 checks passed**. It covers successful registration, duplicate rejection, full capacity, own-record visibility, unauthorized cancellation, admin denial, capacity reduction, released seats, preserved history, closed/past events, draft discovery and anonymous private access. All test users and records are rolled back. This is sequential transactional evidence; a separate simultaneous-load test and full browser end-to-end test have not been run.

`database/schema.sql` is the one-time setup for a fresh project. **Do not rerun it on the already configured project.** It is not an incremental migration.

## Manual acceptance checklist before client handover

- [ ] Deploy Python and configure Supabase email/site settings.
- [ ] Create the real admin and two attendee accounts.
- [ ] Create a capacity-one published future event.
- [ ] Register attendee A, confirm booking, refresh and verify persistence.
- [ ] Try duplicate booking and attendee B while full; verify rejection.
- [ ] Cancel A; verify B can reserve the released place.
- [ ] Check attendee A cannot see/cancel B's registration or enter admin.
- [ ] Test draft, cancellation, completion, capacity reduction and deletion guard.
- [ ] Compare dashboard totals and CSV with the attendee list.
- [ ] Test mobile width, keyboard-only dialogs/forms and browser console.
- [ ] Capture attendee, admin, confirmation and mobile screenshots.

## Files

- `backend/main.py` — Python API and static frontend hosting.
- `backend/test_api.py` — meaningful backend checks.
- `database/schema.sql` — tables, indexes and secured transaction functions.
- `database/acceptance_tests.sql` — rollback-only database acceptance suite.
- `dist/` — the browser interface.
- `Dockerfile`, `requirements.txt`, `.env.example` — deployment configuration.

Documentation consulted: https://supabase.com/docs/guides/auth and https://supabase.com/docs/guides/api/securing-your-api.
