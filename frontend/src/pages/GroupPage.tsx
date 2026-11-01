import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import type { Expense, GroupDetail, Settlement, Transfer } from "../api";
import { useAuth } from "../auth";
import { BalanceText } from "../components/BalanceText";
import { ExpenseForm } from "../components/ExpenseForm";
import { ErrorText, Layout, messageOf } from "../components/Layout";
import { SettleUpForm } from "../components/SettleUpForm";
import { formatCents } from "../money";

interface GroupData {
  group: GroupDetail;
  expenses: Expense[];
  settlements: Settlement[];
}

function useGroupData(groupId: number) {
  const { api } = useAuth();
  const [data, setData] = useState<GroupData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    Promise.all([api.getGroup(groupId), api.listExpenses(groupId), api.listSettlements(groupId)])
      .then(([group, expenses, settlements]) => {
        setData({ group, expenses, settlements });
        setError(null);
      })
      .catch((err: unknown) => setError(messageOf(err)));
  }, [api, groupId]);

  useEffect(reload, [reload]);
  return { data, error, reload };
}

export function GroupPage() {
  const groupId = Number(useParams().groupId);
  const { data, error, reload } = useGroupData(groupId);
  const [preset, setPreset] = useState<Transfer | null>(null);

  if (!data) {
    return (
      <Layout>
        <ErrorText error={error} />
        {!error && <p className="muted">Loading…</p>}
      </Layout>
    );
  }

  const { group, expenses, settlements } = data;
  const nameOf = (userId: number) =>
    group.members.find((m) => m.user_id === userId)?.name ?? `User ${userId}`;
  const money = (cents: number) => formatCents(cents, group.currency);

  return (
    <Layout>
      <p>
        <Link to="/">← All groups</Link>
      </p>
      <h1>{group.name}</h1>
      <ErrorText error={error} />

      <div className="grid">
        <section className="card">
          <h2>Balances</h2>
          <ul className="list plain">
            {group.members.map((m) => (
              <li key={m.user_id} className="list-row">
                <span>{m.name}</span>
                <BalanceText cents={m.balance_cents} currency={group.currency} />
              </li>
            ))}
          </ul>
          {group.suggested_settlements.length > 0 && (
            <>
              <h3>To settle up</h3>
              <ul className="list plain">
                {group.suggested_settlements.map((t) => (
                  <li key={`${t.from_user_id}-${t.to_user_id}`} className="list-row">
                    <span>
                      {nameOf(t.from_user_id)} pays {nameOf(t.to_user_id)} {money(t.amount_cents)}
                    </span>
                    <button type="button" className="secondary" onClick={() => setPreset(t)}>
                      Settle
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
          <AddMemberForm groupId={group.id} onAdded={reload} />
        </section>

        <section className="card">
          <h2>Add an expense</h2>
          <ExpenseForm key={group.members.length} groupId={group.id} members={group.members} onAdded={reload} />
          <h2>Record a payment</h2>
          <SettleUpForm groupId={group.id} members={group.members} preset={preset} onSettled={reload} />
        </section>
      </div>

      <section className="card">
        <h2>Activity</h2>
        {expenses.length + settlements.length === 0 ? (
          <p className="muted">Nothing yet.</p>
        ) : (
          <ul className="list plain">
            {[
              ...expenses.map((e) => ({
                id: `e${e.id}`,
                at: e.created_at,
                text: `${nameOf(e.paid_by)} paid ${money(e.amount_cents)} for “${e.description}”`,
                detail: e.splits.map((s) => `${nameOf(s.user_id)} ${money(s.share_cents)}`).join(", "),
              })),
              ...settlements.map((s) => ({
                id: `s${s.id}`,
                at: s.created_at,
                text: `${nameOf(s.payer_id)} paid ${nameOf(s.payee_id)} ${money(s.amount_cents)}`,
                detail: "settlement",
              })),
            ]
              .sort((a, b) => b.at.localeCompare(a.at))
              .map((item) => (
                <li key={item.id} className="activity">
                  <span>{item.text}</span>
                  <span className="muted small">{item.detail}</span>
                </li>
              ))}
          </ul>
        )}
      </section>
    </Layout>
  );
}

function AddMemberForm({ groupId, onAdded }: { groupId: number; onAdded: () => void }) {
  const { api } = useAuth();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await api.addMember(groupId, email);
      setEmail("");
      setError(null);
      onAdded();
    } catch (err) {
      setError(messageOf(err));
    }
  }

  return (
    <form onSubmit={submit} className="stack">
      <div className="row">
        <input
          type="email"
          placeholder="Add member by email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <button type="submit" className="secondary">
          Add
        </button>
      </div>
      <ErrorText error={error} />
    </form>
  );
}
