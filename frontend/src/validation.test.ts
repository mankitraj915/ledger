import { describe, expect, it } from "vitest";

import {
  amountError,
  emailError,
  hasErrors,
  validateAuth,
  validateExpense,
  validateSettlement,
} from "./validation";

describe("emailError", () => {
  it.each(["ada@example.com", " ada@example.co.uk "])("accepts %j", (email) => {
    expect(emailError(email)).toBeUndefined();
  });

  it.each(["", "ada", "ada@", "ada@example", "a da@example.com"])("rejects %j", (email) => {
    expect(emailError(email)).toBeDefined();
  });
});

describe("amountError", () => {
  it("asks for an amount, then for a valid one", () => {
    expect(amountError("")).toBe("Enter an amount");
    expect(amountError("1.234")).toMatch(/12\.50/);
    expect(amountError("0")).toBeDefined();
    expect(amountError("12.5")).toBeUndefined();
  });
});

describe("validateAuth", () => {
  const ok = { email: "ada@example.com", name: "Ada", password: "correct horse" };

  it("passes complete input in both modes", () => {
    expect(validateAuth("signin", ok)).toEqual({});
    expect(validateAuth("register", ok)).toEqual({});
  });

  it("only asks for a name and a long password when registering", () => {
    const short = { ...ok, name: "", password: "short" };
    expect(validateAuth("signin", short)).toEqual({});
    expect(Object.keys(validateAuth("register", short)).sort()).toEqual(["name", "password"]);
  });

  it("reports every missing field at once", () => {
    const errors = validateAuth("signin", { email: "", name: "", password: "" });
    expect(Object.keys(errors).sort()).toEqual(["email", "password"]);
  });
});

describe("validateExpense / validateSettlement", () => {
  it("checks description, amount and participants", () => {
    expect(validateExpense({ description: "Taxi", amount: "12", participants: 2 })).toEqual({});
    const errors = validateExpense({ description: " ", amount: "x", participants: 0 });
    expect(Object.keys(errors).sort()).toEqual(["amount", "description", "participants"]);
  });

  it("refuses a payment from someone to themselves", () => {
    expect(validateSettlement({ payerId: 1, payeeId: 2, amount: "5" })).toEqual({});
    expect(validateSettlement({ payerId: 1, payeeId: 1, amount: "5" }).payee).toBeDefined();
  });

  it("hasErrors ignores cleared fields", () => {
    expect(hasErrors({ email: undefined })).toBe(false);
    expect(hasErrors({ email: "bad" })).toBe(true);
  });
});
