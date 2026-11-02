import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import type { Expense, GroupDetail, Member, Settlement, Transfer } from "../api";
import { useAuth } from "../auth";
import { ExpenseForm } from "../components/ExpenseForm";
import { ArrowRightIcon, ChevronLeftIcon } from "../components/icons";
import { Layout, messageOf, statusOf, useTitle } from "../components/Layout";
import { SettleUpForm } from "../components/SettleUpForm";
import { useToast } from "../components/Toast";
import {
  BalanceFigure,
  Button,
  Callout,
  EmptyState,
  Field,
  Money,
  Monogram,
  Segmented,
  Skeleton,
  SkeletonRows,
} from "../components/ui";
import { formatCents } from "../money";
import { balanceLabel, joinNames, plural, shortDate, toneOf } from "../present";

interface GroupData {
  group: GroupDetail;
  expenses: Expense[];
  settlements: Settlement[];
}

/** A row in the activity list. Pending rows are shown while their request is in flight. */
export interface ActivityItem {
  id: string;
  at: string;
  title: string;
  sub: string;
  cents: number;
  kind: "expense" | "payment";
  pending?: boolean;
}

/** Shows `item` as pending; call the returned function once the real row has loaded. */
export type TrackPending = (item: Omit<ActivityItem, "id" | "pending">) => () => void;

type Tab = "expense" | "payment";

function useGroupData(groupId: number) {
  const { api } = useAuth();
  const [data, setData] = useState<GroupData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(
    () =>
      Promise.all([api.getGroup(groupId), api.listExpenses(groupId), api.listSettlements(groupId)])
        .then(([group, expenses, settlements]) => {
          setData({ group, expenses, settlements });
          setError(null);
        })
        .catch((err: unknown) => setError(messageOf(err))),
    [api, groupId],
  );

  useEffect(() => {
    void reload();
  }, [reload]);
  return { data, error, reload };
}

export function GroupPage() {
  const groupId = Number(useParams().groupId);
  const { user } = useAuth();
  const { data, error, reload } = useGroupData(groupId);
  const [tab, setTab] = useState<Tab>("expense");
  const [preset, setPreset] = useState<Transfer | null>(null);
  const [pending, setPending] = useState<ActivityItem[]>([]);
  const railRef = useRef<HTMLElement>(null);
  useTitle(data?.group.name ?? null);

  const track = useCallback<TrackPending>((item) => {
    const id = `pending-${crypto.randomUUID()}`;
    setPending((current) => [{ ...item, id, pending: true }, ...current]);
    return () => setPending((current) => current.filter((p) => p.id !== id));
  }, []);

  /** Switch the side panel to a form and put the keyboard there. */
  function openRail(next: Tab, transfer: Transfer | null = null) {
    setTab(next);
    if (transfer) setPreset(transfer);
    requestAnimationFrame(() => {
      const rail = railRef.current;
      if (!rail) return;
      rail.scrollIntoView({ block: "nearest", behavior: "smooth" });
      rail.querySelector<HTMLElement>("[data-autofocus], input, select")?.focus({ preventScroll: true });
    });
  }

  if (!data) {
    return (
      <Layout>
        {error ? (
          <Callout action={<Button size="sm" onClick={() => void reload()}>Try again</Button>}>
            {error}
          </Callout>
        ) : (
          <GroupSkeleton />
        )}
      </Layout>
    );
  }

  const { group, expenses, settlements } = data;
  const me = group.members.find((m) => m.user_id === user?.id);
  const nameOf = (userId: number) =>
    userId === user?.id ? "You" : (group.members.find((m) => m.user_id === userId)?.name ?? `User ${userId}`);
  /** The same name mid-sentence: "split between you and Bob". */
  const nameIn = (userId: number) => (userId === user?.id ? "you" : nameOf(userId));
  const money = (cents: number) => formatCents(cents, group.currency);

  const activity: ActivityItem[] = [
    ...pending,
    ...[
      ...expenses.map((e): ActivityItem => {
        const myShare = e.splits.find((s) => s.user_id === user?.id)?.share_cents;
        const between =
          e.splits.length === group.members.length && group.members.length > 2
            ? "split between everyone"
            : `split between ${joinNames(e.splits.map((s) => nameIn(s.user_id)))}`;
        return {
          id: `e${e.id}`,
          at: e.created_at,
          title: e.description,
          sub: `${nameOf(e.paid_by)} paid · ${between}${myShare ? ` · your share ${money(myShare)}` : ""}`,
          cents: e.amount_cents,
          kind: "expense",
        };
      }),
      ...settlements.map(
        (s): ActivityItem => ({
          id: `s${s.id}`,
          at: s.created_at,
          title: `${nameOf(s.payer_id)} paid ${nameIn(s.payee_id)}`,
          sub: "Payment",
          cents: s.amount_cents,
          kind: "payment",
        }),
      ),
    ].sort((a, b) => b.at.localeCompare(a.at)),
  ];

  return (
    <Layout>
      <Link to="/" className="back-link">
        <ChevronLeftIcon size={14} />
        Groups
      </Link>
      <header className="page-header">
        <div>
          <h1 className="page-title">{group.name}</h1>
          <p className="page-subtitle">
            {plural(group.members.length, "member")} · {group.currency}
          </p>
        </div>
      </header>

      {error && (
        <Callout action={<Button size="sm" onClick={() => void reload()}>Try again</Button>}>
          Couldn’t refresh this group: {error}
        </Callout>
      )}

      <div className="group-layout">
        <div className="group-main">
          {me && <Position me={me} group={group} nameOf={nameOf} />}

          <section className="section" aria-labelledby="balances-title">
            <div className="section-head">
              <h2 id="balances-title" className="section-title">
                Balances
              </h2>
              <span className="section-meta">Always sums to zero</span>
            </div>
            <ul className="rows">
              {group.members.map((m) => (
                <li key={m.user_id} className="row">
                  <Monogram name={m.name} />
                  <span className="row-main">
                    <span className="row-title">
                      <span className="row-title-text">{m.name}</span>
                      {m.user_id === user?.id && <span className="tag">You</span>}
                    </span>
                    <span className="row-sub">{m.email}</span>
                  </span>
                  <BalanceFigure
                    cents={m.balance_cents}
                    currency={group.currency}
                    isViewer={m.user_id === user?.id}
                  />
                </li>
              ))}
            </ul>
            {group.members.length === 1 && (
              <p className="section-note">It’s just you so far. Add the people you share costs with.</p>
            )}
            <AddMemberForm groupId={group.id} onAdded={reload} />
          </section>

          {group.suggested_settlements.length > 0 && (
            <section className="section" aria-labelledby="settle-title">
              <div className="section-head">
                <h2 id="settle-title" className="section-title">
                  Settle up
                </h2>
                <span className="section-meta">
                  {plural(group.suggested_settlements.length, "payment")}{" "}
                  {group.suggested_settlements.length === 1 ? "clears" : "clear"} every balance
                </span>
              </div>
              <ul className="rows">
                {group.suggested_settlements.map((t) => (
                  <li key={`${t.from_user_id}-${t.to_user_id}`} className="row row-transfer">
                    <span className="transfer">
                      <span className="row-title-text">{nameOf(t.from_user_id)}</span>
                      <ArrowRightIcon className="transfer-arrow" />
                      <span className="visually-hidden">pays</span>
                      <span className="row-title-text">{nameOf(t.to_user_id)}</span>
                    </span>
                    <Button
                      size="sm"
                      onClick={() => openRail("payment", t)}
                      aria-label={`Record ${nameOf(t.from_user_id)} paying ${nameOf(t.to_user_id)} ${money(t.amount_cents)}`}
                    >
                      Record
                    </Button>
                    <Money cents={t.amount_cents} currency={group.currency} className="amount" />
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="section section-activity" aria-labelledby="activity-title">
            <div className="section-head">
              <h2 id="activity-title" className="section-title">
                Activity
              </h2>
              {activity.length > 0 && (
                <span className="section-meta">
                  {[
                    expenses.length > 0 && plural(expenses.length, "expense"),
                    settlements.length > 0 && plural(settlements.length, "payment"),
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              )}
            </div>
            {activity.length === 0 ? (
              <EmptyState
                action={
                  <Button size="sm" onClick={() => openRail("expense")}>
                    Add an expense
                  </Button>
                }
              >
                No expenses yet. Add the first one: a dinner, a taxi, the rent.
              </EmptyState>
            ) : (
              <ul className="rows rows-activity">
                {activity.map((item) => (
                  <li key={item.id} className={item.pending ? "row is-pending" : "row"} aria-busy={item.pending || undefined}>
                    <span className="date-col">{item.pending ? "Now" : shortDate(item.at)}</span>
                    <span className="row-main">
                      <span className="row-title">
                        <span className="row-title-text">{item.title}</span>
                      </span>
                      <span className="row-sub">{item.pending ? "Saving…" : item.sub}</span>
                    </span>
                    <Money cents={item.cents} currency={group.currency} className="amount" />
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <aside ref={railRef} className="group-rail" aria-label="Add to this group">
          <div className="panel rail-panel">
            <Segmented
              label="What to add"
              value={tab}
              onChange={setTab}
              options={[
                { value: "expense", label: "Expense" },
                { value: "payment", label: "Payment" },
              ]}
            />
            {/* Re-mount on membership change so defaults include new members. */}
            {tab === "expense" ? (
              <ExpenseForm
                key={group.members.length}
                groupId={group.id}
                currency={group.currency}
                members={group.members}
                onSaved={reload}
                track={track}
              />
            ) : (
              <SettleUpForm
                key={group.members.length}
                groupId={group.id}
                currency={group.currency}
                members={group.members}
                suggestions={group.suggested_settlements}
                preset={preset}
                onSaved={reload}
                track={track}
              />
            )}
          </div>
        </aside>
      </div>
    </Layout>
  );
}

/** The viewer's own balance: the largest thing on the page, in words and colour. */
function Position({
  me,
  group,
  nameOf,
}: {
  me: Member;
  group: GroupDetail;
  nameOf: (userId: number) => string;
}) {
  const tone = toneOf(me.balance_cents);
  const mine = group.suggested_settlements.filter(
    (t) => t.from_user_id === me.user_id || t.to_user_id === me.user_id,
  );
  // Who, not how much: the amounts are listed under "Settle up".
  const payers = mine.filter((t) => t.to_user_id === me.user_id).map((t) => nameOf(t.from_user_id));
  const payees = mine.filter((t) => t.from_user_id === me.user_id).map((t) => nameOf(t.to_user_id));
  const note =
    tone === "settled"
      ? "Nothing to pay or collect in this group."
      : tone === "owed" && payers.length > 0
        ? `${joinNames(payers)} ${payers.length === 1 ? "owes" : "owe"} you.`
        : tone === "owe" && payees.length > 0
          ? `Settle up by paying ${joinNames(payees)}.`
          : null;

  return (
    <section className={`position tone-${tone}`} aria-label="Your balance">
      <p className="position-label">{tone === "settled" ? "You’re settled up" : balanceLabel(me.balance_cents, true)}</p>
      <p className="position-value">
        <Money cents={Math.abs(me.balance_cents)} currency={group.currency} />
      </p>
      {note && <p className="position-note">{note}</p>}
    </section>
  );
}

function AddMemberForm({ groupId, onAdded }: { groupId: number; onAdded: () => Promise<void> }) {
  const { api } = useAuth();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!email.trim()) return setError("Enter the email they signed up with");
    setBusy(true);
    try {
      const member = await api.addMember(groupId, email.trim());
      await onAdded();
      setEmail("");
      setError(undefined);
      toast.success(`${member.name} joined the group`);
    } catch (err) {
      // "No such user" and "already a member" belong next to the field.
      const status = statusOf(err);
      if (status === 404 || status === 409 || status === 422) setError(messageOf(err));
      else toast.error(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="add-member" noValidate>
      <Field label="Add someone" hint="They need a Ledger account with this email." error={error}>
        {(control) => (
          <span className="inline-control">
            <input
              {...control}
              type="email"
              autoComplete="off"
              spellCheck={false}
              placeholder="name@example.com"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setError(undefined);
              }}
            />
            <Button type="submit" loading={busy}>
              Add
            </Button>
          </span>
        )}
      </Field>
    </form>
  );
}

function GroupSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading group">
      <Skeleton width="56px" height="0.75em" />
      <div className="page-header skeleton-header">
        <div>
          <Skeleton width="220px" height="1.6em" />
          <Skeleton width="120px" className="skeleton-sub" />
        </div>
      </div>
      <div className="group-layout">
        <div className="group-main">
          <div className="position">
            <Skeleton width="90px" />
            <Skeleton width="180px" height="2.6em" className="skeleton-sub" />
          </div>
          <SkeletonRows count={3} />
        </div>
        <div className="group-rail">
          <div className="panel rail-panel">
            <Skeleton height="var(--control-height)" />
            <SkeletonRows count={2} withDate />
          </div>
        </div>
      </div>
    </div>
  );
}
