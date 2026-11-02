# Ledger

[![CI](https://github.com/mankitraj915/ledger/actions/workflows/ci.yml/badge.svg)](https://github.com/mankitraj915/ledger/actions/workflows/ci.yml)

**Live demo:** _coming soon_

**Ledger is an expense-splitting app** (a stripped-down Splitwise): create a group, add
shared expenses, see who owes whom, settle up.

**Stack:** Python 3.11 · FastAPI · SQLAlchemy 2 · PostgreSQL 16 · Alembic · React 19 +
TypeScript (Vite) · pytest + Hypothesis · Docker · GitHub Actions.

**The hard problem it solves: settling up correctly under concurrency.** When two
settle-up requests for the same debt arrive at the same instant (a double-tap, a
retry, two devices), a naive implementation pays the debt twice or silently loses a
balance update. In Ledger, a settlement is one ACID transaction that either fully
applies or fully rolls back. Balance rows are locked so concurrent payments serialise
instead of racing. An idempotency key makes a resubmitted request apply exactly once.
And the database itself refuses to commit any state where a group's balances don't sum
to zero. Each guarantee has a test that forces the race deterministically, plus a
negative control showing the same test *fails* when the protection is removed.

## Architecture

```mermaid
flowchart LR
    Browser["Browser<br/>React SPA"] -- "HTTPS, JSON<br/>Bearer JWT" --> App

    subgraph App["One FastAPI service (one container)"]
        direction TB
        MW["Middleware<br/>request id + JSON logs"] --> Routers
        Routers["Routers<br/>auth · groups · expenses · settlements"] --> Services["Domain services<br/>(own the transaction boundary)"]
        Services --> Pure["ledger.allocation / ledger.balances<br/>pure money rules"]
        Services --> Store["ledger.store<br/>the ONLY writer of balances<br/>locks rows, applies zero-sum deltas"]
        Static["Built SPA<br/>(same origin, no CORS)"]
    end

    Store -- "READ COMMITTED<br/>SELECT … FOR UPDATE" --> PG[("PostgreSQL<br/>unique idempotency index<br/>deferred zero-sum trigger")]
    Audit["python -m app.ledger.audit<br/>replays the journal"] -. "REPEATABLE READ snapshot" .-> PG
```

## Engineering highlights

The interesting code, one click away:

| What | Where |
| --- | --- |
| **Concurrency proofs.** Each race is forced at the exact read→write point; with locks, the second transaction is observed blocked in `pg_stat_activity`; negative controls with `FOR UPDATE` removed show the corruption happening. | [`test_settlement_races.py`](backend/tests/concurrency/test_settlement_races.py#L60), the [`Gate`](backend/tests/concurrency/support.py#L25) that forces interleavings, [expense-edit race](backend/tests/concurrency/test_expense_races.py#L23), [randomised 8-thread workload](backend/tests/concurrency/test_stress.py#L93) |
| **Idempotency.** `INSERT … ON CONFLICT DO NOTHING` on a unique `(created_by, idempotency_key)` index: a concurrent duplicate waits on the index for the first transaction, then replays its result. | [`_claim_idempotency_key`](backend/app/settlements/service.py#L115), [`record_settlement`](backend/app/settlements/service.py#L57) |
| **Row locking.** Balance rows are locked `FOR UPDATE` in `user_id` order (deadlock-free) and re-read after the lock is granted. Documented lock hierarchy: group → expense → memberships. | [`lock_balances`](backend/app/ledger/store.py#L61), [module docstring](backend/app/ledger/store.py) |
| **Sum-to-zero trigger.** A deferred constraint trigger refuses to COMMIT any transaction that leaves a group's balances not summing to 0. | [migration](backend/migrations/versions/0001_initial_schema.py#L25) |
| **Overdraw rule.** A settlement can only pay down real, outstanding debt; checked against post-lock balances. | [`ensure_settleable`](backend/app/ledger/balances.py#L68) |
| **Exact money.** Integer cents, largest-remainder splitting, property-tested with Hypothesis. | [`allocate_proportionally`](backend/app/ledger/allocation.py#L20), [tests](backend/tests/unit/test_allocation.py) |
| **Ledger audit.** Replays the journal in one REPEATABLE READ snapshot and compares it with the stored balances. | [`audit.py`](backend/app/ledger/audit.py#L84) |
| **Design write-up.** Five contested decisions, the concurrency problem in plain English, likely interview questions, and known weaknesses. | [WALKTHROUGH.md](WALKTHROUGH.md) |

## Engineering notes: three things that didn't go to plan

**1. A concurrency test that passed with and without the fix.** Locking a balance row
is only useful if you then read the *locked* value. SQLAlchemy's identity map keeps one
object per row per session, so if the request already holds a `Membership` loaded
before the lock (say, from the authorisation check), a plain `SELECT … FOR UPDATE`
returns that cached object with its *pre-lock* balance. `populate_existing=True`
forces the locked read to overwrite it. The first test for this raced two settlements
and passed. Then I removed `populate_existing` and it **still passed**. The reason:
the identity map holds clean objects only by *weak* reference. The service discarded the
membership returned by the auth check, CPython freed it immediately, and the locked
query built a fresh object, so the bug the test targeted couldn't occur in that
scenario. The test was vacuous. I replaced it with
[`test_lock_rereads.py`](backend/tests/concurrency/test_lock_rereads.py), which
deliberately holds a strong reference, commits a change from a second connection, then
locks. It fails without `populate_existing` (`assert -100 == 0`) and passes with it.
Every concurrency test here has been checked the same way: break the fix, watch the
test fail.

**2. The JPY bug.** Amounts are stored as integer *hundredths*. That's right for USD or
EUR, but a group created in JPY (no minor unit) or KWD (three decimals) would have
displayed and split every amount at the wrong scale, and the schema allowed any
three-letter code. The fix was the simplest correct one: accept only two-decimal
currencies ([`SUPPORTED_CURRENCIES`](backend/app/groups/schemas.py#L11)) until there's
a per-currency exponent. A rejected-JPY case is in the API tests.

**3. Who gets the odd cent?** $30.01 split two ways can't be even, and rounding each
share independently can create or destroy a cent. Ledger uses largest-remainder
apportionment: every share is floored, then the leftover cents go one each to the
largest fractional remainders, with ties to the **lowest user id**. Shares always sum
exactly to the total, each is within one cent of fair, and the result is deterministic,
so the same expense always produces the same balances. In the browser check, Bob
(user 1) got $15.01 and Ada (user 2) got $15.00. The frontend never computes
`amount * 100` either (`0.29 * 100 === 28.999…`): it
[parses the decimal string](frontend/src/money.ts#L9) straight into cents. Before you
add an expense, the form previews every share using
[the same rule](frontend/src/present.ts#L27) (floor, then odd cents to the lowest ids),
so the preview matches what the server stores. The server's allocation still decides.

## Interface

The UI is hand-built CSS: no component library, no CSS framework, no web font, no icon
font. One idea drives it: the ledger column. Words sit on the left and right-aligned
tabular figures on the right, separated by hairline rules. Colour is information only:
- a grey ramp carries the interface;
- one ink blue marks primary actions and focus;
- green and red mean only "owed to you" and "you owe", and always come with those words.

Every size, space, colour, radius and shadow is a token in
[`styles.css`](frontend/src/styles.css). Light and dark are separate palettes, chosen per
token with `light-dark()`.

## Status: what is verified

| Check | Result |
| --- | --- |
| Backend tests (unit, integration, concurrency) against real Postgres 16 | 132 passed, locally and in CI |
| Every setup and test command in this README, run from a fresh clone | works |
| `ruff check`, `ruff format --check`, `mypy --strict` | clean, locally and in CI |
| Alembic upgrade → `alembic check` → downgrade | clean, in CI |
| Frontend type-check, 47 Vitest tests, production build | clean, locally |
| UI at 360px and 1280px, light and dark: no horizontal scroll, screenshots reviewed | locally, headless Chrome |
| Contrast computed from the tokens: text ≥ 4.5:1, form-control borders ≥ 3:1 (placeholders ≈ 3.4:1) | both themes |
| Production Docker image build | succeeds, locally and in CI |
| `docker compose up`: health, SPA, registration | worked locally |
| Full UI flow in a real browser (register, group, member, expense, settle up) | worked locally |
| Hosted deployment | not yet |

No performance or uptime numbers are claimed, because none have been measured.

## How a settlement executes

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant S as settlements.service
    participant DB as PostgreSQL
    C->>S: POST /groups/{id}/settlements (Idempotency-Key: k)
    S->>DB: SELECT group FOR KEY SHARE (exists, blocks a concurrent delete)
    S->>DB: INSERT settlement ON CONFLICT (created_by, key) DO NOTHING RETURNING *
    alt key already used
        DB-->>S: no row (waited for the first attempt to commit)
        S-->>C: 200 + original settlement, Idempotent-Replayed: true
    else new key
        S->>DB: SELECT payer, payee memberships ORDER BY user_id FOR UPDATE
        Note over S,DB: a concurrent settlement on these rows waits here
        S->>S: overdraw rule on the post-lock balances
        S->>DB: UPDATE both balances (deltas sum to 0)
        S->>DB: COMMIT (deferred trigger re-checks the group sums to 0)
        S-->>C: 201 Created
    end
```

### Data model

```
users(id, email UNIQUE, name, password_hash)
groups(id, name, currency, created_by)
memberships(group_id, user_id, balance_cents)        PK(group_id, user_id)
expenses(id, group_id, description, amount_cents, paid_by, split_method, version, ...)
splits(expense_id, user_id, share_cents, weight)     PK(expense_id, user_id)
settlements(id, group_id, payer_id, payee_id, amount_cents, created_by,
            idempotency_key, request_fingerprint)    UNIQUE(created_by, idempotency_key)
```

- **Money is `BIGINT` cents** end to end.
- **Sign convention:** `balance_cents > 0` means the group owes you; `< 0` means you owe.
- **Balances are materialised** on `memberships` as a cache of the journal (expenses +
  splits + settlements). The audit checks that cache against the journal.

## Key decisions and trade-offs

| Decision | Why | Rejected alternatives |
| --- | --- | --- |
| **Materialised balance per membership, plus the journal** | Reading balances is O(members), not O(history), and settlements update balances atomically. A stored balance is exactly what can suffer a lost update, so it has to be defended properly. | *Derived-only balances*: race-free reads but slower with history, and the settlement check is still a check-then-act race needing locks anyway. |
| **READ COMMITTED + explicit `SELECT … FOR UPDATE`**, rows locked in `user_id` order | The rows a settlement touches are known up front. A pessimistic lock makes the second writer *wait and re-read*: no retry loop, deterministic outcome, and ordered locking rules out deadlock. | *SERIALIZABLE*: correct, but every writer needs a `40001` retry loop, and it only protects if *every* transaction touching the rows is SERIALIZABLE. *Optimistic versioning*: retry storms under exactly the contention that matters. *Group mutex*: serialises unrelated settlements. |
| **Idempotency through a unique index + `INSERT … ON CONFLICT DO NOTHING`** | Postgres makes a concurrent duplicate wait for the first transaction and then conflict, atomically with the money movement. A stored SHA-256 of the body turns key reuse with a different body into a 422. | *SELECT-then-INSERT*: both duplicates insert. *Redis lock*: extra infrastructure that can disagree with the DB. *Full response caching*: more than this endpoint needs. |
| **Zero-sum enforced in code and by a deferred constraint trigger** | Code catches bugs early. The trigger means no code path or manual SQL can *commit* an unbalanced group. Deferred, because a transfer is two UPDATEs. | *App-only*: one bug from silent drift. *Periodic fix-up*: detects damage after users have seen it. |
| **Largest-remainder allocation in integer cents** | Exact sums, ≤ 1 cent from fair, deterministic. | *Per-share rounding*: loses or creates cents. *Fractional `NUMERIC`*: defers rounding to settlement time. |
| **One service that also serves the built SPA** | Same origin (no CORS), one deployable. | Separate static host/CDN: unnecessary at this size. |

## API

All errors share one envelope: `{"error": {"code", "message", "details?"}}`.
Interactive docs at `/api/docs`.

| Method & path | Success | Notable errors |
| --- | --- | --- |
| `POST /api/auth/register` | 201 token + user | 409 `email_taken`, 422 |
| `POST /api/auth/login` | 200 token + user | 401 `invalid_credentials` |
| `GET /api/auth/me` | 200 | 401 |
| `POST /api/groups` · `GET /api/groups` | 201 · 200 | 422 (only 2-decimal currencies) |
| `GET /api/groups/{id}` (members, balances, suggested transfers) | 200 | 404, for non-members too |
| `PATCH /api/groups/{id}` · `DELETE /api/groups/{id}` | 200 · 204 | 403 not creator, 409 `group_not_settled` |
| `POST /api/groups/{id}/members` | 201 | 404 unknown email, 409 `already_member` |
| `GET` / `POST /api/groups/{id}/expenses` | 200 / 201 | 422 `invalid_split`, 422 `not_group_member` |
| `PUT /api/groups/{id}/expenses/{eid}` (body includes `version`) | 200 | 409 `stale_version` |
| `POST /api/groups/{id}/settlements` (header `Idempotency-Key`) | 201, or 200 + `Idempotent-Replayed: true` on replay | 400 `idempotency_key_required`, 403 not a party, 409 `settlement_exceeds_balance`, 422 `idempotency_key_reused` |
| `GET /api/groups/{id}/settlements` | 200 | |
| `GET /api/health` | 200, or 503 if the DB is unreachable | |

## Running it

### Everything in Docker

```bash
docker compose up --build
# open http://localhost:8000
```

### Local development

Requires Python 3.11+, Node 22+, and Docker for the database (or any PostgreSQL 16 you
can reach; adjust the URLs below).

```bash
# database only
docker compose up -d db

# backend
cd backend
python -m venv .venv
source .venv/bin/activate              # Windows (Git Bash): source .venv/Scripts/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql://ledger:ledger@localhost:5432/ledger
export JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
alembic upgrade head
uvicorn app.main:create_app --factory --reload      # http://localhost:8000/api/docs

# frontend, in a second terminal: Vite proxies /api to :8000
cd frontend
npm ci
npm run dev                                         # http://localhost:5173
```

| Variable | Required | Notes |
| --- | --- | --- |
| `DATABASE_URL` | yes | `postgres://` and `postgresql://` are both accepted |
| `JWT_SECRET` | yes, ≥ 32 chars | the app refuses to start without it |
| `JWT_TTL_MINUTES` | no | default 720 |
| `LOG_LEVEL` | no | default `INFO` |
| `CORS_ORIGINS` | no | unnecessary when the SPA is served by the API |
| `STATIC_DIR` | no | set in the Docker image |

### Tests

The tests need a disposable database. They wipe it and build the schema by running the
real Alembic migrations, trigger included.

```bash
docker compose exec db createdb -U ledger ledger_test

cd backend                                          # with the virtualenv active
export TEST_DATABASE_URL=postgresql://ledger:ledger@localhost:5432/ledger_test
pytest                                              # everything
pytest tests/unit                                   # pure money logic, no database
pytest -m concurrency -v                            # the race proofs

cd ../frontend && npm test
```

### Ledger audit

Needs only `DATABASE_URL`. Exit status: 0 consistent, 1 mismatch found, 2 usage error.

```bash
cd backend                                          # with the virtualenv active
DATABASE_URL=postgresql://ledger:ledger@localhost:5432/ledger python -m app.ledger.audit
```

## Deploy

[`render.yaml`](render.yaml) is a Render Blueprint: a Docker web service plus managed
Postgres, with `DATABASE_URL` wired in and `JWT_SECRET` generated. In Render choose
**New → Blueprint** and select this repository. The container runs migrations on boot
(under a Postgres advisory lock) and honours `$PORT`, so other container hosts work
the same way. On free tiers the service sleeps when idle and free databases are
time-limited, so check the host's current terms.

## Layout

```
backend/
  app/
    auth/ groups/ expenses/ settlements/   one package per domain: models, schemas, service, router
    ledger/
      allocation.py   integer-cent splitting (pure)
      balances.py     zero-sum deltas, overdraw rule, debt simplification (pure)
      store.py        lock hierarchy; the only code that writes balances
      audit.py        journal replay vs stored balances
    main.py db.py config.py errors.py observability.py health.py
  migrations/          Alembic, including the zero-sum trigger
  tests/ unit/ integration/ concurrency/
frontend/src/          api.ts, money.ts, present.ts, validation.ts, auth.tsx, pages/, components/, styles.css
```

## What's next

- **History, not overwrite:** expense edits mutate in place, so the journal explains
  *current* balances but not who changed what. Append-only entries (reversal + new
  entry) would give a full audit trail.
- **Delete or reverse expenses and settlements**, as compensating entries.
- **Auth hardening:** login rate limiting, short-lived access tokens with refresh and
  revocation, and httpOnly cookies instead of `localStorage`.
- **Idempotency key retention:** keys live forever today. Expire them after N days.
- **Scheduled audit** with alerting on any mismatch.
- **Per-currency minor units** (JPY, KWD), then multi-currency groups.
- **Browser E2E tests** (Playwright) in CI. The UI flow has only been checked by hand.
