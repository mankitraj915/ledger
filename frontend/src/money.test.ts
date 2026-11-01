import { describe, expect, it } from "vitest";

import { centsToInput, formatCents, parseAmountToCents } from "./money";

describe("parseAmountToCents", () => {
  it.each([
    ["12", 1200],
    ["12.5", 1250],
    ["12.34", 1234],
    ["0.29", 29], // 0.29 * 100 === 28.999999999999996 in floating point
    ["0.01", 1],
    [" 7.10 ", 710],
    ["999999999.99", 99_999_999_999],
  ])("parses %j as %i cents", (input, cents) => {
    expect(parseAmountToCents(input)).toBe(cents);
  });

  it.each(["", "0", "0.00", "-5", "1.234", "1,50", "abc", "1e3", ".5", "1.", "1234567890"])(
    "rejects %j",
    (input) => {
      expect(parseAmountToCents(input)).toBeNull();
    },
  );
});

describe("centsToInput", () => {
  it.each([
    [1234, "12.34"],
    [5, "0.05"],
    [100, "1.00"],
  ])("formats %i as %j", (cents, text) => {
    expect(centsToInput(cents)).toBe(text);
    expect(parseAmountToCents(text)).toBe(cents);
  });
});

describe("formatCents", () => {
  it("formats in the group's currency", () => {
    expect(formatCents(123456, "USD")).toMatch(/1,?234\.56/);
    expect(formatCents(-500, "USD")).toMatch(/5\.00/);
  });
});
