import { describe, expect, it } from "vitest";

import type { Member } from "./api";
import {
  balanceLabel,
  currencySymbol,
  equalShares,
  initials,
  joinNames,
  plural,
  settlementEffect,
  shortDate,
  toneOf,
} from "./present";

describe("toneOf / balanceLabel", () => {
  it("names the direction in words, from the viewer's side and a member's", () => {
    expect([toneOf(500), toneOf(-500), toneOf(0)]).toEqual(["owed", "owe", "settled"]);
    expect(balanceLabel(500, true)).toBe("You're owed");
    expect(balanceLabel(-500, true)).toBe("You owe");
    expect(balanceLabel(500, false)).toBe("Is owed");
    expect(balanceLabel(-500, false)).toBe("Owes");
    expect(balanceLabel(0, true)).toBe("Settled up");
  });
});

describe("equalShares", () => {
  it("splits evenly when it can", () => {
    expect([...equalShares(3000, [3, 1, 2]).entries()].sort()).toEqual([
      [1, 1000],
      [2, 1000],
      [3, 1000],
    ]);
  });

  it("gives the odd cent to the lowest user id, as the server does", () => {
    // README example: $30.01 between users 1 and 2 -> user 1 pays $15.01.
    const shares = equalShares(3001, [2, 1]);
    expect(shares.get(1)).toBe(1501);
    expect(shares.get(2)).toBe(1500);
  });

  it("always sums to the total", () => {
    const shares = equalShares(1000, [5, 9, 7]);
    expect([...shares.values()].reduce((a, b) => a + b, 0)).toBe(1000);
    expect(shares.get(5)).toBe(334);
  });

  it("is empty with nobody to split between", () => {
    expect(equalShares(1000, []).size).toBe(0);
  });
});

describe("settlementEffect", () => {
  const members: Member[] = [
    { user_id: 1, name: "Ada", email: "a@x.io", balance_cents: 3000 },
    { user_id: 2, name: "Bob", email: "b@x.io", balance_cents: -3000 },
  ];

  it("raises the payer's balance and lowers the payee's by the same amount", () => {
    expect(settlementEffect(members, 2, 1, 3000)).toEqual([
      { userId: 2, name: "Bob", before: -3000, after: 0 },
      { userId: 1, name: "Ada", before: 3000, after: 0 },
    ]);
  });

  it("ignores ids that are not members", () => {
    expect(settlementEffect(members, 2, 99, 100)).toHaveLength(1);
  });
});

describe("formatting helpers", () => {
  it("finds the currency symbol for the amount prefix", () => {
    expect(currencySymbol("USD", "en-US")).toBe("$");
    expect(currencySymbol("EUR", "en-US")).toBe("€");
  });

  it("builds monograms from names", () => {
    expect(initials("Ada Lovelace")).toBe("AL");
    expect(initials("bob")).toBe("B");
    expect(initials("Grace Brewster Hopper")).toBe("GH");
    expect(initials("  ")).toBe("");
  });

  it("pluralises and joins like a sentence", () => {
    expect(plural(1, "member")).toBe("1 member");
    expect(plural(3, "member")).toBe("3 members");
    expect(joinNames(["Ada"])).toBe("Ada");
    expect(joinNames(["Ada", "Bob"])).toBe("Ada and Bob");
    expect(joinNames(["Ada", "Bob", "Cy"])).toBe("Ada, Bob and Cy");
  });

  it("formats activity dates briefly and tolerates garbage", () => {
    expect(shortDate("2026-11-02T10:00:00Z", "en-US")).toBe("Nov 2");
    expect(shortDate("not a date")).toBe("");
  });
});
