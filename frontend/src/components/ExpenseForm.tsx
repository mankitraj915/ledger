import { useId, useRef, useState, type FormEvent } from "react";

import type { Member } from "../api";
import { useAuth } from "../auth";
import { formatCents, parseAmountToCents } from "../money";
import type { TrackPending } from "../pages/GroupPage";
import { currencySymbol, equalShares } from "../present";
import { hasErrors, validateExpense, type Errors, type ExpenseField } from "../validation";
import { CheckIcon } from "./icons";
import { messageOf } from "./Layout";
import { useToast } from "./Toast";
import { AmountInput, Button, Field, Select } from "./ui";

interface Props {
  groupId: number;
  currency: string;
  members: Member[];
  onSaved: () => Promise<void>;
  track: TrackPending;
}

export function ExpenseForm({ groupId, currency, members, onSaved, track }: Props) {
  const { api, user } = useAuth();
  const toast = useToast();
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [paidBy, setPaidBy] = useState<number>(user?.id ?? members[0]?.user_id ?? 0);
  const [participants, setParticipants] = useState<Set<number>>(
    () => new Set(members.map((m) => m.user_id)),
  );
  const [errors, setErrors] = useState<Errors<ExpenseField>>({});
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const splitId = useId();

  const values = { description, amount, participants: participants.size };
  const recheck = (next: typeof values) => submitted && setErrors(validateExpense(next));

  function toggle(userId: number) {
    const next = new Set(participants);
    if (next.has(userId)) next.delete(userId);
    else next.add(userId);
    setParticipants(next);
    recheck({ ...values, participants: next.size });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitted(true);
    const found = validateExpense(values);
    setErrors(found);
    const cents = parseAmountToCents(amount);
    if (hasErrors(found) || cents === null) {
      formRef.current?.querySelector<HTMLElement>("[aria-invalid='true'], [data-invalid] input")?.focus();
      return;
    }
    setBusy(true);
    const payer = members.find((m) => m.user_id === paidBy)?.name ?? "Someone";
    const done = track({
      at: new Date().toISOString(),
      title: description.trim(),
      sub: `${payer} paid`,
      cents,
      kind: "expense",
    });
    try {
      await api.addExpense(groupId, {
        description: description.trim(),
        amount_cents: cents,
        paid_by: paidBy,
        split: { method: "equal", participants: [...participants] },
      });
      await onSaved();
      toast.success(`Added “${description.trim()}” · ${formatCents(cents, currency)}`);
      setDescription("");
      setAmount("");
      setSubmitted(false);
      setErrors({});
    } catch (err) {
      toast.error(messageOf(err));
    } finally {
      done();
      setBusy(false);
    }
  }

  const cents = parseAmountToCents(amount);
  const shares = cents === null ? null : equalShares(cents, [...participants]);
  const payerName = paidBy === user?.id ? "You" : (members.find((m) => m.user_id === paidBy)?.name ?? "");

  return (
    <form ref={formRef} onSubmit={submit} className="form" noValidate>
      <Field label="Description" error={errors.description}>
        {(control) => (
          <input
            {...control}
            data-autofocus
            placeholder="Dinner, taxi, rent…"
            maxLength={200}
            value={description}
            onChange={(e) => {
              setDescription(e.target.value);
              recheck({ ...values, description: e.target.value });
            }}
          />
        )}
      </Field>
      <div className="form-row">
        <Field label="Amount" error={errors.amount}>
          {(control) => (
            <AmountInput
              control={control}
              symbol={currencySymbol(currency)}
              value={amount}
              onChange={(next) => {
                setAmount(next);
                recheck({ ...values, amount: next });
              }}
            />
          )}
        </Field>
        <Field label="Paid by">
          {(control) => (
            <Select
              control={control}
              value={paidBy}
              onChange={(v) => setPaidBy(Number(v))}
              options={members.map((m) => ({
                value: m.user_id,
                label: m.user_id === user?.id ? "You" : m.name,
              }))}
            />
          )}
        </Field>
      </div>

      <fieldset className="field" aria-describedby={`${splitId}-msg`} data-invalid={errors.participants ? "" : undefined}>
        <legend className="field-label">Split equally between</legend>
        <div className="chips">
          {members.map((m) => (
            <label key={m.user_id} className="chip">
              <input type="checkbox" checked={participants.has(m.user_id)} onChange={() => toggle(m.user_id)} />
              <span className="chip-face">
                <span className="chip-check">
                  <CheckIcon size={10} strokeWidth={2.25} />
                </span>
                {m.user_id === user?.id ? "You" : m.name}
              </span>
            </label>
          ))}
        </div>
        <p id={`${splitId}-msg`} className={errors.participants ? "field-msg is-error" : "field-msg"}>
          {errors.participants ?? ""}
        </p>
      </fieldset>

      <div className="preview" aria-live="polite">
        {shares && shares.size > 0 && cents !== null ? (
          <>
            <p>
              <strong>{payerName}</strong> paid <strong className="num">{formatCents(cents, currency)}</strong>
              {shares.size === 1 ? ", all of it for one person." : `, split ${shares.size} ways:`}
            </p>
            <ul className="preview-lines">
              {members
                .filter((m) => shares.has(m.user_id))
                .map((m) => (
                  <li key={m.user_id} className="preview-line">
                    <span>{m.user_id === user?.id ? "You" : m.name}</span>
                    <span className="num">{formatCents(shares.get(m.user_id) ?? 0, currency)}</span>
                  </li>
                ))}
            </ul>
          </>
        ) : (
          <p>Enter an amount to see exactly who owes what.</p>
        )}
      </div>

      <Button type="submit" variant="primary" block loading={busy}>
        Add expense
      </Button>
    </form>
  );
}
