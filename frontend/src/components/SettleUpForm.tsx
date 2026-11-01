import { useEffect, useState, type FormEvent } from "react";

import type { Member, Transfer } from "../api";
import { useAuth } from "../auth";
import { centsToInput, parseAmountToCents } from "../money";
import { ErrorText, messageOf } from "./Layout";

interface Props {
  groupId: number;
  members: Member[];
  /** A suggested transfer the user clicked; prefills the form. */
  preset: Transfer | null;
  onSettled: () => void;
}

/**
 * One Idempotency-Key per settle-up *attempt*. The key is reused if the same request
 * is resubmitted (a retry after a timeout, a double click that slipped through) so
 * the server applies it once; it is regenerated when the request itself changes or
 * after it succeeds, so a deliberate second payment is not mistaken for a retry.
 */
function newKey(): string {
  return crypto.randomUUID();
}

export function SettleUpForm({ groupId, members, preset, onSettled }: Props) {
  const { api, user } = useAuth();
  const [payerId, setPayerId] = useState<number>(user?.id ?? 0);
  const [payeeId, setPayeeId] = useState<number>(
    members.find((m) => m.user_id !== user?.id)?.user_id ?? 0,
  );
  const [amount, setAmount] = useState("");
  const [key, setKey] = useState(newKey);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!preset) return;
    setPayerId(preset.from_user_id);
    setPayeeId(preset.to_user_id);
    setAmount(centsToInput(preset.amount_cents));
  }, [preset]);

  // A different request needs a different key.
  useEffect(() => setKey(newKey()), [payerId, payeeId, amount]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const cents = parseAmountToCents(amount);
    if (cents === null) return setError("Enter an amount like 12.50");
    if (payerId === payeeId) return setError("Choose two different people");
    setBusy(true);
    setError(null);
    try {
      await api.settle(groupId, { payer_id: payerId, payee_id: payeeId, amount_cents: cents }, key);
      setAmount("");
      setKey(newKey());
      onSettled();
    } catch (err) {
      setError(messageOf(err)); // the key is kept, so "try again" is a safe retry
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="stack">
      <div className="row">
        <select value={payerId} onChange={(e) => setPayerId(Number(e.target.value))} aria-label="Payer">
          {members.map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.name}
            </option>
          ))}
        </select>
        <span className="muted">paid</span>
        <select value={payeeId} onChange={(e) => setPayeeId(Number(e.target.value))} aria-label="Payee">
          {members.map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.name}
            </option>
          ))}
        </select>
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
      <ErrorText error={error} />
      <button type="submit" disabled={busy}>
        Record payment
      </button>
    </form>
  );
}
