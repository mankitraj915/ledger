import { useEffect, useRef, useState, type FormEvent } from "react";

import type { Member, Transfer } from "../api";
import { useAuth } from "../auth";
import { centsToInput, formatCents, parseAmountToCents } from "../money";
import type { TrackPending } from "../pages/GroupPage";
import { currencySymbol, settlementEffect, toneOf } from "../present";
import { hasErrors, validateSettlement, type Errors, type SettlementField } from "../validation";
import { ArrowRightIcon } from "./icons";
import { messageOf } from "./Layout";
import { useToast } from "./Toast";
import { AmountInput, Button, Field, Select } from "./ui";

interface Props {
  groupId: number;
  currency: string;
  members: Member[];
  suggestions: Transfer[];
  /** A suggested transfer the user picked; prefills the form. */
  preset: Transfer | null;
  onSaved: () => Promise<void>;
  track: TrackPending;
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

export function SettleUpForm({ groupId, currency, members, suggestions, preset, onSaved, track }: Props) {
  const { api, user } = useAuth();
  const toast = useToast();
  // Default to the payment the viewer most likely came to make: their own suggested one.
  const [initial] = useState<Transfer | undefined>(
    () => preset ?? suggestions.find((t) => t.from_user_id === user?.id),
  );
  const [payerId, setPayerId] = useState<number>(initial?.from_user_id ?? user?.id ?? 0);
  const [payeeId, setPayeeId] = useState<number>(
    initial?.to_user_id ?? members.find((m) => m.user_id !== user?.id)?.user_id ?? 0,
  );
  const [amount, setAmount] = useState(initial ? centsToInput(initial.amount_cents) : "");
  const [key, setKey] = useState(newKey);
  const [errors, setErrors] = useState<Errors<SettlementField>>({});
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (!preset) return;
    setPayerId(preset.from_user_id);
    setPayeeId(preset.to_user_id);
    setAmount(centsToInput(preset.amount_cents));
  }, [preset]);

  // A different request needs a different key.
  useEffect(() => setKey(newKey()), [payerId, payeeId, amount]);

  useEffect(() => {
    if (submitted) setErrors(validateSettlement({ payerId, payeeId, amount }));
  }, [submitted, payerId, payeeId, amount]);

  const nameOf = (id: number) =>
    id === user?.id ? "You" : (members.find((m) => m.user_id === id)?.name ?? "Someone");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitted(true);
    const found = validateSettlement({ payerId, payeeId, amount });
    setErrors(found);
    const cents = parseAmountToCents(amount);
    if (hasErrors(found) || cents === null) {
      formRef.current?.querySelector<HTMLElement>("[aria-invalid='true']")?.focus();
      return;
    }
    setBusy(true);
    const summary = `${nameOf(payerId)} paid ${nameOf(payeeId).replace(/^You$/, "you")}`;
    const done = track({ at: new Date().toISOString(), title: summary, sub: "Payment", cents, kind: "payment" });
    try {
      await api.settle(groupId, { payer_id: payerId, payee_id: payeeId, amount_cents: cents }, key);
      await onSaved();
      toast.success(`Recorded: ${summary} ${formatCents(cents, currency)}`);
      setAmount("");
      setKey(newKey());
      setSubmitted(false);
      setErrors({});
    } catch (err) {
      // The key is kept, so pressing the button again is a safe retry.
      toast.error(`Payment not recorded: ${messageOf(err).replace(/\.$/, "")}. Retrying is safe; it can’t be recorded twice.`);
    } finally {
      done();
      setBusy(false);
    }
  }

  const options = members.map((m) => ({
    value: m.user_id,
    label: m.user_id === user?.id ? "You" : m.name,
  }));
  const cents = parseAmountToCents(amount);
  const changes = cents !== null && payerId !== payeeId ? settlementEffect(members, payerId, payeeId, cents) : [];

  return (
    <form ref={formRef} onSubmit={submit} className="form" noValidate>
      <div className="form-row">
        <Field label="From">
          {(control) => <Select control={control} value={payerId} onChange={(v) => setPayerId(Number(v))} options={options} />}
        </Field>
        <Field label="To" error={errors.payee}>
          {(control) => <Select control={control} value={payeeId} onChange={(v) => setPayeeId(Number(v))} options={options} />}
        </Field>
      </div>
      <Field label="Amount" error={errors.amount}>
        {(control) => (
          <AmountInput control={control} symbol={currencySymbol(currency)} value={amount} onChange={setAmount} />
        )}
      </Field>

      <div className="preview" aria-live="polite">
        {changes.length === 2 && cents !== null ? (
          <>
            <p>
              <strong>{nameOf(payerId)}</strong> {payerId === user?.id ? "pay" : "pays"}{" "}
              <strong>{nameOf(payeeId).replace(/^You$/, "you")}</strong>{" "}
              <strong className="num">{formatCents(cents, currency)}</strong>. Afterwards:
            </p>
            <ul className="preview-lines">
              {changes.map((c) => (
                <li key={c.userId} className="preview-line">
                  <span>{nameOf(c.userId)}</span>
                  <span className="preview-change">
                    <BalanceWords cents={c.before} currency={currency} />
                    <ArrowRightIcon size={12} className="transfer-arrow" />
                    <span className="visually-hidden">becomes</span>
                    <BalanceWords cents={c.after} currency={currency} />
                  </span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p>Record money that changed hands outside Ledger. Balances update when you save.</p>
        )}
      </div>

      <Button type="submit" variant="primary" block loading={busy}>
        Record payment
      </Button>
    </form>
  );
}

function BalanceWords({ cents, currency }: { cents: number; currency: string }) {
  const tone = toneOf(cents);
  if (tone === "settled") return <span className="tone-settled">settled</span>;
  const words = tone === "owed" ? "owed" : "owes";
  return (
    <span className={`num tone-${tone}`}>
      {words} {formatCents(Math.abs(cents), currency)}
    </span>
  );
}
