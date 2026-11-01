import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import type { GroupSummary } from "../api";
import { useAuth } from "../auth";
import { ErrorText, Layout, messageOf } from "../components/Layout";
import { BalanceText } from "../components/BalanceText";

const CURRENCIES = ["USD", "EUR", "GBP", "INR", "CAD", "AUD"];

export function GroupsPage() {
  const { api } = useAuth();
  const navigate = useNavigate();
  const [groups, setGroups] = useState<GroupSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState("USD");

  const load = useCallback(() => {
    api.listGroups().then(setGroups, (err: unknown) => setError(messageOf(err)));
  }, [api]);

  useEffect(load, [load]);

  async function create(event: FormEvent) {
    event.preventDefault();
    try {
      const group = await api.createGroup(name, currency);
      navigate(`/groups/${group.id}`);
    } catch (err) {
      setError(messageOf(err));
    }
  }

  return (
    <Layout>
      <h1>Your groups</h1>
      <ErrorText error={error} />
      {groups === null ? (
        <p className="muted">Loading…</p>
      ) : groups.length === 0 ? (
        <p className="muted">No groups yet. Create one to start splitting expenses.</p>
      ) : (
        <ul className="list">
          {groups.map((group) => (
            <li key={group.id}>
              <Link to={`/groups/${group.id}`} className="list-row">
                <span>
                  <strong>{group.name}</strong>
                  <span className="muted"> · {group.member_count} members</span>
                </span>
                <BalanceText cents={group.my_balance_cents} currency={group.currency} />
              </Link>
            </li>
          ))}
        </ul>
      )}

      <section className="card">
        <h2>New group</h2>
        <form onSubmit={create} className="row">
          <input
            placeholder="Group name"
            required
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <select value={currency} onChange={(e) => setCurrency(e.target.value)} aria-label="Currency">
            {CURRENCIES.map((code) => (
              <option key={code}>{code}</option>
            ))}
          </select>
          <button type="submit">Create</button>
        </form>
      </section>
    </Layout>
  );
}
