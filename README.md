# Ledger

A deliberately small expense-splitting app (think stripped-down Splitwise): create a
group, add shared expenses, see who owes whom, settle up. The interesting part is the
**money spine**: balances in a group always sum to zero, a settlement either fully
happens or doesn't happen at all, a double-submitted settlement applies once, and two
simultaneous settlements can't corrupt a balance. Each of those is enforced by the
database and proved by a test.

**Stack:** Python 3.11 · FastAPI · SQLAlchemy 2 · PostgreSQL 16 · Alembic · React 19 +
Vite + TypeScript · pytest + Hypothesis · Vitest · Docker · GitHub Actions.

## Status: what is and isn't verified

Everything below was run on a developer laptop (Windows 11) against PostgreSQL 16.

| Check | Result |
| --- | --- |
| Backend tests (unit, integration, concurrency) against real Postgres | 129 passed (`pytest`) |
| `ruff check`, `ruff format --check`, `mypy --strict` | clean |
| Alembic upgrade → downgrade → upgrade, `alembic check` | clean |
| Frontend `tsc --noEmit`, `vitest` (22 tests), `vite build` | clean |
| `docker build` of the production image | succeeds |
| `docker compose up`: health check, SPA served, registration | worked |
| Full UI flow in a real browser (register, group, add member, expense, settle up) | worked |
| GitHub Actions workflow | **not run yet**: the repository hasn't been pushed |
| Hosted deployment | **not deployed yet**: see [Deploy](#deploy) |

There are no performance or uptime numbers here because none have been measured.

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

The settle-up path, which is where the rigour goes:

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant S as settlements.service
    participant DB as PostgreSQL
    C->>S: POST /groups/{id}/settlements<br/>Idempotency-Key: k
    S->>DB: SELECT group FOR KEY SHARE (exists; blocks a concurrent delete)
    S->>DB: INSERT settlement … ON CONFLICT (created_by, key) DO NOTHING RETURNING *
    alt key already used
        DB-->>S: (no row; waited for the first attempt to commit)
        S-->>C: 200 + original settlement, Idempotent-Replayed: true
    else new key
        S->>DB: SELECT payer, payee memberships ORDER BY user_id FOR UPDATE
        Note over S,DB: a concurrent settlement on these rows waits here
        S->>S: overdraw rule on the post-lock balances
        S->>DB: UPDATE both balances (deltas sum to 0)
        S->>DB: COMMIT (deferred trigger re-checks group sums to 0)
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

- **Money is `BIGINT` cents.** No floats anywhere, including the frontend, which parses
  `"12.34"` into `1234` by string, not by `* 100`.
- **Sign convention:** `balance_cents > 0` means the group owes you; `< 0` means you owe.
- **Balances are materialised** on `memberships` and are a cache of the journal
  (expenses + splits + settlements). `app.ledger.audit` replays the journal and
  checks that it matches.

## Key decisions and trade-offs

| Decision | Why | Rejected alternatives |
| --- | --- | --- |
| **Materialised balance per membership, plus the journal** | Reading balances is O(members), not O(history). The brief also calls for settlements that update balances atomically, and a stored balance is exactly the thing that can suffer a lost update, so it has to be defended properly. | *Derived-only balances* (sum history on every read): simpler and race-free for reads, but slower as history grows, and settlement validation is still a check-then-act race that needs locking anyway. |
| **READ COMMITTED + explicit `SELECT … FOR UPDATE`**, rows locked in `user_id` order | The rows a settlement touches are known up front. Pessimistic locks make the second writer *wait and then re-read*, so there's no retry loop and the outcome is deterministic. Ordered locking rules out deadlock between settlements and expenses. | *SERIALIZABLE*: correct, but every writer then needs a retry loop for `40001` failures, and the guarantee only holds if *every* transaction touching these rows is SERIALIZABLE. *Optimistic version column*: retries under exactly the contention we care about (double-submits). *Group-level mutex*: simpler, but serialises unrelated settlements in a group. |
| **Idempotency through a unique index with `INSERT … ON CONFLICT DO NOTHING`** | Postgres makes a concurrent duplicate insert wait for the first transaction and then conflict, which is exactly the semantics needed, with no extra infrastructure. The request body's SHA-256 is stored, so reusing a key for a different body returns 422. | *SELECT-then-INSERT*: both duplicates see "no row" and both insert. *Redis/locks*: an extra moving part, and its state can disagree with the DB. *Cache full responses*: more general (Stripe-style), but more than this endpoint needs. |
| **Zero-sum enforced twice**: in code (`assert_zero_sum` before any write) and by a `DEFERRABLE INITIALLY DEFERRED` constraint trigger | The app check catches bugs early. The trigger makes the database refuse to *commit* an unbalanced group, whatever code path or manual SQL produced it. Deferred, because a balanced transfer is two UPDATEs, and the state in between is legitimately unbalanced. | *App-only*: one bug or one psql session away from silent drift. *Recompute and correct periodically*: detects drift after the fact instead of preventing it. |
| **Largest-remainder allocation in integer cents**, ties to the lowest user id | Shares sum *exactly* to the total and are each within 1 cent of fair. Deterministic, so the same expense always yields the same balances. | *Round each share*: shares can sum to total ±n cents. *`NUMERIC` with fractional cents*: defers the problem to settlement time. |
| **One service** that also serves the built SPA | Same origin means no CORS and one deployable. Matches the "one service built excellently" brief. | Separate static host or CDN: worthwhile at scale, unnecessary here. |

What Postgres actually guarantees here, and where races hide, is covered in
[WALKTHROUGH.md](WALKTHROUGH.md).

## API

All errors share one envelope: `{"error": {"code", "message", "details?"}}`.

| Method & path | Success | Notable errors |
| --- | --- | --- |
| `POST /api/auth/register` | 201 token + user | 409 `email_taken`, 422 |
| `POST /api/auth/login` | 200 token + user | 401 `invalid_credentials` |
| `GET /api/auth/me` | 200 | 401 |
| `POST /api/groups` · `GET /api/groups` | 201 · 200 | 422 (only 2-decimal currencies) |
| `GET /api/groups/{id}` (members, balances, suggested transfers) | 200 | 404 for non-members too |
| `PATCH /api/groups/{id}` · `DELETE /api/groups/{id}` | 200 · 204 | 403 not creator, 409 `group_not_settled` |
| `POST /api/groups/{id}/members` | 201 | 404 unknown email, 409 `already_member` |
| `GET/POST /api/groups/{id}/expenses` | 200 / 201 | 422 `invalid_split`, 422 `not_group_member` |
| `PUT /api/groups/{id}/expenses/{eid}` (body includes `version`) | 200 | 409 `stale_version` |
| `POST /api/groups/{id}/settlements` (header `Idempotency-Key`) | 201, or 200 on replay with `Idempotent-Replayed: true` | 400 `idempotency_key_required`, 403 not a party, 409 `settlement_exceeds_balance`, 422 `idempotency_key_reused` |
| `GET /api/groups/{id}/settlements` | 200 | |
| `GET /api/health` | 200, or 503 if the DB is unreachable | |

Interactive docs: `/api/docs`.

## Running it

### Everything in Docker

```bash
docker compose up --build
# open http://localhost:8000
```

### Local development

Requires Python 3.11+, Node 22+, and a PostgreSQL 16 you can reach (for example, just
the `db` service: `docker compose up db`).

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql://ledger:ledger@localhost:5432/ledger
export JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
alembic upgrade head
uvicorn app.main:create_app --factory --reload          # http://localhost:8000/api/docs

# frontend (second terminal): Vite proxies /api to :8000
cd frontend && npm ci && npm run dev                     # http://localhost:5173
```

| Variable | Required | Default |
| --- | --- | --- |
| `DATABASE_URL` | yes | `postgres://` and `postgresql://` are both accepted |
| `JWT_SECRET` | yes, ≥ 32 chars | none: the app refuses to start without it |
| `JWT_TTL_MINUTES` | no | 720 |
| `LOG_LEVEL` | no | `INFO` |
| `CORS_ORIGINS` | no | none (the SPA is same-origin) |
| `STATIC_DIR` | no | set in the Docker image |

### Tests

The tests need a disposable Postgres database. They wipe it, and build its schema by
running the real Alembic migrations, trigger included.

```bash
cd backend
createdb ledger_test   # or use the compose db
export TEST_DATABASE_URL=postgresql://ledger:ledger@localhost:5432/ledger_test
pytest                       # everything
pytest tests/unit            # pure money logic, no DB
pytest -m concurrency -v     # the race proofs

cd ../frontend && npm test
```

### Ledger audit

```bash
cd backend && python -m app.ledger.audit   # exit 1 if any group's balances disagree with its journal
```

## Deploy

`render.yaml` is a Render Blueprint: one Docker web service plus a managed Postgres,
with `DATABASE_URL` wired in and `JWT_SECRET` generated.

1. Push this repository to GitHub.
2. In Render: **New → Blueprint**, select the repository, and apply.
3. When the deploy is healthy (`/api/health` returns 200), the service URL serves the app.

Free-tier caveats: free web services sleep when idle, so the first request after a
pause is slow, and free databases are time-limited. Check Render's current terms. The
Dockerfile is host-agnostic (it honours `$PORT`), so Fly.io, Railway or Koyeb with Neon
work the same way.

## Layout

```
backend/
  app/
    auth/  groups/  expenses/  settlements/   one package per domain: models, schemas, service, router
    ledger/
      allocation.py   integer-cent splitting (pure)
      balances.py     zero-sum deltas, overdraw rule, debt simplification (pure)
      store.py        lock hierarchy; the only code that writes balances
      audit.py        journal replay vs stored balances
    main.py  db.py  config.py  errors.py  observability.py  health.py
  migrations/          Alembic, incl. the zero-sum trigger
  tests/  unit/  integration/  concurrency/
frontend/src/          api.ts, money.ts, auth.tsx, pages/, components/
```

## What's next

- **History, not overwrite:** expense edits currently mutate in place, and the journal
  only reconstructs the *current* state. An append-only event log (or reversal
  entries) would give an audit trail of who changed what.
- **Delete or reverse expenses and settlements**, implemented as compensating entries.
- **Auth hardening:** rate-limit login, short-lived access tokens with refresh and
  revocation, and httpOnly cookies instead of `localStorage`.
- **Idempotency key retention:** keys live forever today. Expire them after N days.
- **Run the audit on a schedule** and alert on any mismatch.
- **Per-currency minor units** (JPY, KWD), then multi-currency groups.
- **Browser E2E tests** (Playwright) in CI. The UI flow has only been checked by hand.
