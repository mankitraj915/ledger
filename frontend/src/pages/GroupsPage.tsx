import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import type { GroupSummary } from "../api";
import { useAuth } from "../auth";
import { ChevronRightIcon, PlusIcon } from "../components/icons";
import { Layout, messageOf, useTitle } from "../components/Layout";
import { useToast } from "../components/Toast";
import {
  BalanceFigure,
  Button,
  Callout,
  EmptyState,
  Field,
  Monogram,
  Select,
  SkeletonRows,
} from "../components/ui";
import { plural } from "../present";

// The server accepts only currencies with two minor-unit digits.
const CURRENCIES = ["USD", "EUR", "GBP", "INR", "CAD", "AUD"];

export function GroupsPage() {
  const { api } = useAuth();
  const [groups, setGroups] = useState<GroupSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  useTitle("Groups");

  const load = useCallback(() => {
    setLoadError(null);
    api.listGroups().then(setGroups, (err: unknown) => setLoadError(messageOf(err)));
  }, [api]);

  useEffect(load, [load]);

  const empty = groups !== null && groups.length === 0;

  return (
    <Layout narrow>
      <header className="page-header">
        <div>
          <h1 className="page-title">Groups</h1>
          <p className="page-subtitle">Everyone you share costs with, and where you stand.</p>
        </div>
        {!creating && !empty && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            <PlusIcon />
            New group
          </Button>
        )}
      </header>

      {creating && !empty && <CreateGroup onCancel={() => setCreating(false)} />}

      {loadError && (
        <Callout action={<Button size="sm" onClick={load}>Try again</Button>}>{loadError}</Callout>
      )}

      {groups === null ? (
        !loadError && <SkeletonRows count={3} />
      ) : empty ? (
        <>
          <EmptyState>
            No groups yet. Make one for a trip, a shared flat or a dinner, then add people by email.
          </EmptyState>
          <CreateGroup />
        </>
      ) : (
        <ul className="rows">
          {groups.map((group) => (
            <li key={group.id}>
              <Link to={`/groups/${group.id}`} className="row row-link">
                <Monogram name={group.name} square />
                <span className="row-main">
                  <span className="row-title">
                    <span className="row-title-text">{group.name}</span>
                  </span>
                  <span className="row-sub">
                    {plural(group.member_count, "member")} · {group.currency}
                  </span>
                </span>
                <span className="row-end">
                  <BalanceFigure cents={group.my_balance_cents} currency={group.currency} isViewer />
                  <ChevronRightIcon className="row-chevron" />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Layout>
  );
}

function CreateGroup({ onCancel }: { onCancel?: () => void }) {
  const { api } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [error, setError] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (onCancel) nameRef.current?.focus();
  }, [onCancel]);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) {
      setError("Give the group a name");
      nameRef.current?.focus();
      return;
    }
    setBusy(true);
    try {
      const group = await api.createGroup(name.trim(), currency);
      toast.success(`Created “${name.trim()}”`);
      navigate(`/groups/${group.id}`);
    } catch (err) {
      toast.error(messageOf(err));
      setBusy(false);
    }
  }

  return (
    <section className="panel create-panel" aria-labelledby="create-group-title">
      <div className="section-head">
        <h2 id="create-group-title" className="section-title">
          New group
        </h2>
        {onCancel && (
          <Button variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
      <form onSubmit={create} className="create-grid" noValidate>
        <Field label="Name" error={error}>
          {(control) => (
            <input
              {...control}
              ref={nameRef}
              placeholder="Lisbon trip"
              maxLength={100}
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                if (e.target.value.trim()) setError(undefined);
              }}
            />
          )}
        </Field>
        <Field label="Currency">
          {(control) => (
            <Select
              control={control}
              value={currency}
              onChange={setCurrency}
              options={CURRENCIES.map((c) => ({ value: c, label: c }))}
            />
          )}
        </Field>
        <Button type="submit" variant="primary" loading={busy}>
          Create group
        </Button>
      </form>
    </section>
  );
}
