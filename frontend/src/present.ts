/** Pure presentation helpers: how balances, splits and payments are described. */

import type { Member } from "./api";

export type Tone = "owed" | "owe" | "settled";

/** A balance is positive when the person is owed money, negative when they owe it. */
export function toneOf(balanceCents: number): Tone {
  if (balanceCents > 0) return "owed";
  if (balanceCents < 0) return "owe";
  return "settled";
}

/** Words that carry the meaning, so colour is never the only signal. */
export function balanceLabel(balanceCents: number, isViewer: boolean): string {
  const tone = toneOf(balanceCents);
  if (tone === "settled") return "Settled up";
  if (isViewer) return tone === "owed" ? "You're owed" : "You owe";
  return tone === "owed" ? "Is owed" : "Owes";
}

/**
 * The cents each participant pays when `totalCents` is split equally. Mirrors the
 * server's allocation exactly: everyone gets the floor, and the leftover cents go one
 * each to the lowest user ids. Shown before submitting so nobody is surprised.
 */
export function equalShares(totalCents: number, participantIds: number[]): Map<number, number> {
  const shares = new Map<number, number>();
  if (participantIds.length === 0 || totalCents <= 0) return shares;
  const sorted = [...participantIds].sort((a, b) => a - b);
  const base = Math.floor(totalCents / sorted.length);
  const leftover = totalCents - base * sorted.length;
  sorted.forEach((id, index) => shares.set(id, base + (index < leftover ? 1 : 0)));
  return shares;
}

export interface BalanceChange {
  userId: number;
  name: string;
  before: number;
  after: number;
}

/** What recording "payer paid payee `cents`" does to the two balances it touches. */
export function settlementEffect(
  members: Member[],
  payerId: number,
  payeeId: number,
  cents: number,
): BalanceChange[] {
  const change = (userId: number, delta: number): BalanceChange | null => {
    const member = members.find((m) => m.user_id === userId);
    if (!member) return null;
    return {
      userId,
      name: member.name,
      before: member.balance_cents,
      after: member.balance_cents + delta,
    };
  };
  // Paying a debt raises the payer's balance and lowers the payee's by the same amount.
  return [change(payerId, cents), change(payeeId, -cents)].filter(
    (c): c is BalanceChange => c !== null,
  );
}

/** "$", "€", "₹"… for the amount field's prefix. Falls back to the ISO code. */
export function currencySymbol(currency: string, locale?: string): string {
  try {
    const parts = new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      currencyDisplay: "narrowSymbol",
    }).formatToParts(0);
    return parts.find((p) => p.type === "currency")?.value ?? currency;
  } catch {
    return currency;
  }
}

/** "Ada Lovelace" -> "AL", "bob" -> "B". */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const letters = words.length > 1 ? [words[0], words[words.length - 1]] : words.slice(0, 1);
  return letters.map((w) => [...(w ?? "")][0]?.toUpperCase() ?? "").join("");
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** "Nov 2" for the activity date column. */
export function shortDate(iso: string, locale?: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(locale, { month: "short", day: "numeric" }).format(date);
}

/** Lists names the way a sentence would: "Ada", "Ada and Bob", "Ada, Bob and Cy". */
export function joinNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}
