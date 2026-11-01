import { useState, type FormEvent } from "react";

import type { Member } from "../api";
import { useAuth } from "../auth";
import { parseAmountToCents } from "../money";
import { ErrorText, messageOf } from "./Layout";

interface Props {
  groupId: number;
  members: Member[];
  onAdded: () => void;
}

export function ExpenseForm({ groupId, members, onAdded }: Props) {
  const { api, user } = useAuth();
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [paidBy, setPaidBy] = useState<number>(user?.id ?? members[0]?.user_id ?? 0);
  const [participants, setParticipants] = useState<Set<number>>(
    () => new Set(members.map((m) => m.user_id)),
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function toggle(userId: number) {
    setParticipants((current) => {
      const next = new Set(current);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const cents = parseAmountToCents(amount);
    if (cents === null) return setError("Enter an amount like 12.50");
    if (participants.size === 0) return setError("Pick at least one person to split with");
    setBusy(true);
    setError(null);
    try {
      await api.addExpense(groupId, {
        description,
        amount_cents: cents,
        paid_by: paidBy,
        split: { method: "equal", participants: [...participants] },
      });
      setDescription("");
      setAmount("");
      onAdded();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="stack">
      <div className="row">
        <input
          placeholder="What was it for?"
          required
          maxLength={200}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <input
          placeholder="0.00"
          inputMode="decimal"
          required
          className="amount"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          aria-label="Amount"
        />
      </div>
      <label className="inline">
        Paid by
        <select value={paidBy} onChange={(e) => setPaidBy(Number(e.target.value))}>
          {members.map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.name}
            </option>
          ))}
        </select>
      </label>
      <fieldset>
        <legend>Split equally between</legend>
        {members.map((m) => (
          <label key={m.user_id} className="check">
            <input
              type="checkbox"
              checked={participants.has(m.user_id)}
              onChange={() => toggle(m.user_id)}
            />
            {m.name}
          </label>
        ))}
      </fieldset>
      <ErrorText error={error} />
      <button type="submit" disabled={busy}>
        Add expense
      </button>
    </form>
  );
}
