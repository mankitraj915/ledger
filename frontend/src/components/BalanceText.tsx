import { formatCents } from "../money";

/** A balance from the viewer's perspective: positive means they are owed. */
export function BalanceText({ cents, currency }: { cents: number; currency: string }) {
  if (cents === 0) return <span className="muted">settled up</span>;
  return cents > 0 ? (
    <span className="owed">is owed {formatCents(cents, currency)}</span>
  ) : (
    <span className="owes">owes {formatCents(-cents, currency)}</span>
  );
}
