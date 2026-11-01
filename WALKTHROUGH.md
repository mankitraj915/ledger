# Ledger: walkthrough for an interview

This is the document to read before talking about the project. File references point
at the code that backs each claim.

---

## 1. The five decisions most likely to be challenged

### 1.1 Storing balances instead of computing them from history

**Choice.** Each `memberships` row has a `balance_cents`, a running total updated in the
same transaction as every expense and settlement. The journal (expenses, splits,
settlements) is kept as well, and `app/ledger/audit.py` replays it to check the stored
numbers.

**Why.** Reads become O(members) rather than O(history), and the brief asks for
settlements that "update balances atomically". More importantly, a stored balance is
the thing that suffers lost updates, so choosing it forces the concurrency question to
be answered properly instead of sidestepped.

**Rejected.** *Derive balances on every read.* Reads would be race-free, but the
settle-up check ("you can't pay more than you owe") is still read-then-write, so the
same locking is needed anyway, and reads slow down as history grows. The cost of my
choice is that two representations of the truth must agree. That's why the audit
exists, and why the concurrency tests check "stored == journal", not just "sums to 0".

### 1.2 READ COMMITTED + `SELECT … FOR UPDATE`, not SERIALIZABLE

**Choice.** The engine is pinned to READ COMMITTED (`app/db.py`). Every money write
locks the exact balance rows it will change, in ascending `user_id` order, re-reads
them after the lock is granted, validates, writes and commits (`app/ledger/store.py`).

**Why.** The rows involved are known before the transaction starts (payer and payee,
or payer and participants). With a pessimistic lock the second writer simply *waits*
and then sees the committed result, with no retry loop and a deterministic outcome
(either "succeeds against the new balance" or "rejected: exceeds outstanding").

**Rejected.**
- *SERIALIZABLE (SSI).* Correct, but it aborts one side with `40001` and leaves the
  application to retry. Every writer needs a retry wrapper, false positives happen,
  and the protection only holds if *all* transactions touching these rows run
  SERIALIZABLE. One forgotten code path at READ COMMITTED reopens the hole.
- *REPEATABLE READ.* Postgres does raise `could not serialize access due to concurrent
  update` when two transactions update the same row, which prevents the lost update,
  but again only by aborting and retrying.
- *Optimistic `version` column on balances.* Fine with low contention, but
  double-submits are precisely the high-contention case, so it degenerates into retry
  storms.
- *One lock per group.* Simpler and also correct, but it serialises unrelated
  settlements in the same group. (Group *deletion* does take an exclusive group lock,
  where coarse is exactly what's wanted.)

### 1.3 Idempotency through a unique index, not application logic

**Choice.** `UNIQUE (created_by, idempotency_key)` on `settlements`. The settlement row
is inserted with `INSERT … ON CONFLICT DO NOTHING RETURNING *` *before* any balance is
touched (`app/settlements/service.py`). No row back means a replay: load the original,
compare the request fingerprint (SHA-256 of the body), and return it with 200 and
`Idempotent-Replayed: true`. A different body under the same key gets 422.

**Why.** When the first transaction has inserted key *k* but not committed, Postgres
makes a second `INSERT` of *k* **wait** on the unique index. If the first commits, the
second gets "conflict, do nothing"; if it rolls back, the second proceeds. The
database already implements exactly the semantics needed, atomically with the money
movement, because it's the same transaction.

**Rejected.** *SELECT-then-INSERT*: two concurrent duplicates both see "no row" and
both insert. *Redis or an in-memory lock*: extra infrastructure, and it can disagree
with the database after a crash. *Storing whole responses (Stripe-style)*: more
general, but this endpoint's response is just the settlement row, which is already
stored.

**Trade-off I'd own.** Only *successful* settlements consume a key. A request rejected
for overdraw rolls back, so retrying the same key later can succeed (there's a test
for this). That's a choice: Stripe records failures too. Keys also never expire.

### 1.4 A database trigger for the zero-sum invariant

**Choice.** A `CONSTRAINT TRIGGER … DEFERRABLE INITIALLY DEFERRED` on `memberships`
(`migrations/versions/0001_initial_schema.py`) re-sums the group at COMMIT and raises
`check_violation` if the total isn't 0. The application *also* asserts zero-sum
before applying any deltas (`assert_zero_sum` in `app/ledger/balances.py`).

**Why.** The app check is the first line. The trigger means no code path, future
refactor or manual `psql` session can commit an unbalanced group. It's *deferred*
because a transfer is two UPDATEs and the state between them is legitimately
unbalanced. A concurrency test shows it catching a real lost update
(`test_negative_control_without_locks_the_zero_sum_trigger_refuses_the_commit`).

**Rejected.** *App-only enforcement*: one bug away from silent drift. *A nightly fix-up
job*: detects damage after customers have seen it.

**Limits I'd say out loud.** The trigger runs once per changed row at commit (O(rows ×
members)), which is fine for groups of people but not for thousand-member groups. And
it can't detect a lost update that *preserves* the sum (one of the negative controls
shows exactly that case). That's what the journal audit is for.

### 1.5 Integer cents with largest-remainder allocation

**Choice.** All amounts are `BIGINT` cents. Splits use Hamilton's largest-remainder
method: floor every share, then hand the leftover cents one each to the largest
fractional remainders, with ties going to the lowest user id
(`app/ledger/allocation.py`). Only two-decimal currencies are accepted.

**Why.** The shares *always* sum exactly to the total, each is within 1 cent of its
fair value, and the result is deterministic. Hypothesis property tests check all three
properties over random inputs.

**Rejected.** *Floats*: `0.1 + 0.2 != 0.3`, and `0.29 * 100` is `28.999…`. That's why
the frontend parses `"0.29"` into 29 by string manipulation (`frontend/src/money.ts`).
*Round each share independently*: 100/3 gives 33+33+33 = 99, and a cent vanishes.
*`NUMERIC` with fractional cents*: only postpones rounding to settlement time.

---

## 2. The concurrency problem, in plain English

**The setup.** Bob owes Ada $100. Bob opens the app on his phone and his laptop and
taps "Settle $100" on both at the same moment, or taps once on a flaky connection and
the app retries.

**What a naive implementation does.** Each request runs:

1. read Bob's balance (−100) and Ada's (+100);
2. check that 100 ≤ what Bob owes. OK;
3. write Bob = −100 + 100 = 0 and Ada = 100 − 100 = 0;
4. commit.

Run two of these at once and both do step 1 *before* either does step 3. Both read
"Bob owes 100", both pass the check, and both record a $100 payment. Then:

- **Overdraw:** $200 has been "paid" against a $100 debt, and two settlement records
  exist.
- **Lost update:** both requests *write the absolute value 0*. The second simply
  overwrites the first, so the stored balances say 0/0 while the history says Bob
  paid $200. The books are now wrong, and nothing looks wrong: the balances still sum
  to zero.

Postgres's default isolation level, READ COMMITTED, doesn't prevent this. Each
statement sees the latest committed data, but nothing stops another transaction from
committing between your read and your write.

**The fix, and why it works.** Step 1 becomes `SELECT … FOR UPDATE`. That takes an
exclusive lock on Bob's and Ada's rows, held until the transaction commits.

- The second request reaches step 1 and **blocks** because the first holds the lock.
- The first finishes: it writes 0/0 and commits, which releases the lock.
- The second's SELECT now returns and, because under READ COMMITTED the statement reads
  the latest committed row version once the lock is granted, it sees **Bob = 0**.
- The check "Bob must owe something" fails, so the second request gets a 409 and
  changes nothing.

So "read, check, write" becomes one indivisible step with respect to anyone else
touching the same rows. Three details make it actually hold:

1. **Lock order.** Rows are locked sorted by `user_id`. If one transaction locked
   Ada-then-Bob and another Bob-then-Ada, each could hold one lock while waiting for
   the other, a deadlock. With one global order that cycle can't form. (Postgres
   applies `FOR UPDATE` in the `ORDER BY` order because the lock step sits above the
   sort in the plan.)
2. **The ORM cache.** SQLAlchemy keeps one object per row per session. If the request
   still holds Bob's row from before the lock (say, from the authorisation check), a
   plain locked SELECT hands back that *old* object, and the lock would protect
   nothing. The locked query uses `populate_existing` so the fresh values win.
   `tests/concurrency/test_lock_rereads.py` fails without it (verified by removing it).
3. **The same key, twice.** If both taps carry the same `Idempotency-Key`, the second
   one blocks even earlier, at the `INSERT` into `settlements`, on the unique index.
   When the first commits, the second gets "already exists" and returns the first
   one's result instead of paying again.

**How the tests prove it, rather than hope it.** Racing two threads and checking the
result usually passes even with the bug, because the window is microseconds wide. The
tests instead patch a *gate* into the code at the exact moment between "read balance"
and "write balance", then:

- with locks: assert that **only one** transaction ever reaches the gate, and that the
  other is visible in `pg_stat_activity` waiting on a lock with a `FOR UPDATE … memberships`
  query. Then open the gate and assert one success, one rejection, and stored ==
  journal.
- **negative control**, with `FOR UPDATE` removed: the same choreography lets *both*
  reach the gate, both "succeed", and the audit shows stored ≠ journal. This proves the
  test can see the bug, so its passing isn't luck.

(`backend/tests/concurrency/test_settlement_races.py`. A randomised eight-thread
workload in `test_stress.py` adds evidence for interleavings nobody thought of.)

**Other places races hide in this codebase, and how each is closed:**

| Race | Fix |
| --- | --- |
| Two edits of one expense both reverse the old splits (double reversal) | Lock the expense row before reading its splits, plus a `version` check (409 for the loser). Test fails without the lock (verified). |
| Group deleted while an expense is being added | Money writers hold `FOR KEY SHARE` on the group row; delete takes `FOR UPDATE`, so they serialise. A writer that loses gets a clean 404. |
| Duplicate registration with the same email | Unique index plus catching `UniqueViolation`, not "check if the email exists first". |
| Participant whose share rounds to 0 cents | Still locked and membership-checked: the lock set is everyone named, not just non-zero deltas. |

---

## 3. Ten likely interview questions, with model answers

**Q1. Why not just compute balances from history on every request?**
That would work, and for reads it's simpler. But the settle-up rule ("can't pay more
than you owe") still reads and then writes, so the race and the lock are needed either
way. Storing balances keeps reads cheap and puts the invariant in one place. The cost
is a second representation that can drift, which the journal audit and the
stored-vs-journal assertions in the tests guard against.

**Q2. What does Postgres actually guarantee at READ COMMITTED, and why is it enough?**
Each statement sees a snapshot of data committed before it started, and row-level
write locks are always taken. On its own that doesn't stop read-modify-write races
across statements. What makes it enough here is `SELECT … FOR UPDATE`: if the row is
locked, the statement waits, and once the lock is granted it reads the latest committed
version of the row (Postgres re-checks the updated row), so validation always sees the
current value. Note too that `UPDATE x SET balance = balance + 1` is safe on its own,
but a *check* on the balance isn't.

**Q3. Why not SERIALIZABLE?**
It would catch these anomalies, but by aborting a transaction (`40001`) that the
application must retry. Every writer then needs retry logic, the guarantee only holds
if every participating transaction is SERIALIZABLE, and under the contention we're
explicitly designing for (double-submits) it means wasted work and retries. Explicit
row locks give a deterministic wait-then-decide instead. I'd consider SERIALIZABLE if
the rows to lock weren't known up front, as with predicate-style rules like "total
spend this month < limit".

**Q4. Walk me through a double-click on Settle.**
The client generates one UUID per settle-up attempt and sends it as
`Idempotency-Key`. The UI also disables the button, but that isn't the guarantee.
Request A inserts the settlement row. Request B's insert of the same key blocks on the
unique index. A locks the balances, validates, writes and commits. B's insert now
returns no row (conflict), so B loads A's settlement, checks that the body fingerprint
matches, and returns it with 200 and `Idempotent-Replayed: true`. Balances change once.
There's a test where eight threads submit the same key at the same instant: one
`created`, seven replays, one row.

**Q5. How do you know the concurrency test isn't passing by luck?**
Two ways. First, the race is forced deterministically: a gate pauses each transaction
between read and write, and the test asserts that only one can get there while the
other is observably blocked on a row lock in `pg_stat_activity`. Second, every proof
has a negative control: the same test with `FOR UPDATE` removed must show corruption,
and it does. I also verified the re-read and expense-lock tests fail when the
corresponding fix is removed.

**Q6. What if the server crashes halfway through a settlement?**
The settlement row and both balance updates are in one transaction. If the process
dies before COMMIT, Postgres rolls everything back, including the claimed idempotency
key, so the client's retry with the same key goes through normally. If it dies *after*
COMMIT but before the response is sent, the client retries, hits the unique key, and
gets the original settlement back. Exactly-once from the client's point of view.

**Q7. How do you avoid deadlocks?**
A fixed lock hierarchy: group row (shared), then expense row (edits only), then
membership rows in ascending `user_id`. Any two transactions acquire overlapping locks
in the same order, so no wait-for cycle can form. Postgres would detect a deadlock and
abort one side (`40P01`), but the design aims to never get there. The stress test
mixes expenses with participants in random order, edits and bidirectional settlements,
and fails on any unexpected error, deadlocks included.

**Q8. How is editing an expense made safe?**
An edit is "reverse the old movement, apply the new one", computed as one combined
delta and applied in one transaction. The expense row is locked *before* its splits are
read, so two concurrent edits can't both reverse the same old splits. Clients send the
`version` they edited, and a mismatch is a 409, so nobody silently overwrites someone
else's change. The balance rows locked are the union of old and new participants.

**Q9. Where are the scaling limits?**
Contention is per balance row, and groups are a handful of people, so in practice row
locks rarely wait. The real limits: the deferred trigger re-sums the group per changed
row at commit, which is fine for small groups but would want a per-group running total
for big ones. The audit is a full replay, so it would want incremental checkpoints.
And there's one Postgres. Horizontally, the app is stateless (JWT, no sessions), so
more instances is just more containers, and migrations are already serialised by an
advisory lock.

**Q10. How do you handle rounding?**
Nothing is ever rounded *away*: amounts are integer cents, and splits use largest
remainder, so shares sum exactly to the total. The leftover cents go to the largest
fractional remainders, with ties to the lowest user id, so the result is reproducible.
Property tests check sum-exactness and the within-1-cent bound for random totals and
weights. The UI never multiplies by 100: it parses the decimal string.

---

## 4. The three weakest points, and what I'd say about them

### 4.1 The UI is tested by hand, and nothing has been measured under load

**Honest answer:** The money logic, API and concurrency behaviour are tested in CI
against real Postgres on every push, but the React UI has only unit tests for money
parsing plus a manual run through the main flow in a browser. There are no load or
latency numbers either, because none have been measured, and I won't quote any.

**How I'd address it:** a Playwright E2E test of register → expense → settle up in CI,
and a small k6 script hammering settle-up on one group, to report real p95 latency and
lock-wait numbers.

### 4.2 Auth is the minimum, not production-grade

**Honest answer:** Argon2id hashing, pinned JWT algorithms, constant-work login and
enumeration-safe 404s are all in. But tokens live in `localStorage` (XSS-readable),
there's no refresh or revocation (a stolen token is valid for 12 hours), login isn't
rate-limited, and adding a member by email reveals whether that email has an account.

**How I'd address it:** short-lived access tokens with a rotating refresh token in an
httpOnly, SameSite cookie, plus CSRF protection. Login rate limiting per IP and per
account. Invite-by-link instead of add-by-email.

### 4.3 The ledger records the present, not the past

**Honest answer:** Editing an expense overwrites it, and the journal can only explain
*current* balances, not who changed what and when. There's no delete or reverse for
expenses and settlements either. Settlements are immutable, but a mistaken one has no
supported fix. For a money app, an append-only history matters more than features.

**How I'd address it:** model every change as an immutable entry. An edit becomes a
reversal entry plus a new entry, so `balance = SUM(entries)` holds by construction and
the stored balance is a pure cache. The audit then becomes an exact replay of an
append-only log, and "undo" is just another entry.
