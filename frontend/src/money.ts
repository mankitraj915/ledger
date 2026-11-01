/**
 * Money crosses the wire as integer cents. Converting user input must never go
 * through floating point: "0.29" * 100 is 28.999999999999996 in IEEE-754.
 */

const AMOUNT_PATTERN = /^(\d{1,9})(?:\.(\d{1,2}))?$/;

/** Parse "12", "12.5" or "12.34" into cents; null for anything else or for zero. */
export function parseAmountToCents(input: string): number | null {
  const match = AMOUNT_PATTERN.exec(input.trim());
  if (!match) return null;
  const whole = Number(match[1]);
  const fraction = Number((match[2] ?? "").padEnd(2, "0"));
  const cents = whole * 100 + fraction;
  return cents > 0 ? cents : null;
}

/** Cents back into an input string ("1234" -> "12.34"), for prefilling forms. */
export function centsToInput(cents: number): string {
  const whole = Math.trunc(cents / 100);
  const fraction = String(cents % 100).padStart(2, "0");
  return `${whole}.${fraction}`;
}

export function formatCents(cents: number, currency: string): string {
  // Division is safe for display: |cents| is far below 2^53 and we print 2 decimals.
  return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(cents / 100);
}
