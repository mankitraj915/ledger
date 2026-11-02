/** Client-side checks that give inline messages before a request is made. */

import { parseAmountToCents } from "./money";

export type Errors<K extends string> = Partial<Record<K, string>>;

// Deliberately loose: the server is the authority, this only catches typos early.
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export const MIN_PASSWORD_LENGTH = 8;

export function emailError(email: string): string | undefined {
  if (!email.trim()) return "Enter your email address";
  if (!EMAIL_PATTERN.test(email.trim())) return "Enter an email like name@example.com";
  return undefined;
}

export function amountError(amount: string): string | undefined {
  if (!amount.trim()) return "Enter an amount";
  if (parseAmountToCents(amount) === null) return "Use a positive amount like 12.50";
  return undefined;
}

export type AuthField = "email" | "name" | "password";

export function validateAuth(
  mode: "signin" | "register",
  values: { email: string; name: string; password: string },
): Errors<AuthField> {
  const errors: Errors<AuthField> = {};
  const email = emailError(values.email);
  if (email) errors.email = email;
  if (mode === "register" && !values.name.trim()) errors.name = "Enter the name people know you by";
  if (!values.password) errors.password = "Enter your password";
  else if (mode === "register" && values.password.length < MIN_PASSWORD_LENGTH)
    errors.password = `Use at least ${MIN_PASSWORD_LENGTH} characters`;
  return errors;
}

export type ExpenseField = "description" | "amount" | "participants";

export function validateExpense(values: {
  description: string;
  amount: string;
  participants: number;
}): Errors<ExpenseField> {
  const errors: Errors<ExpenseField> = {};
  if (!values.description.trim()) errors.description = "Say what it was for";
  const amount = amountError(values.amount);
  if (amount) errors.amount = amount;
  if (values.participants === 0) errors.participants = "Pick at least one person";
  return errors;
}

export type SettlementField = "payee" | "amount";

export function validateSettlement(values: {
  payerId: number;
  payeeId: number;
  amount: string;
}): Errors<SettlementField> {
  const errors: Errors<SettlementField> = {};
  if (values.payerId === values.payeeId) errors.payee = "Choose someone other than the payer";
  const amount = amountError(values.amount);
  if (amount) errors.amount = amount;
  return errors;
}

export function hasErrors(errors: Record<string, string | undefined>): boolean {
  return Object.values(errors).some(Boolean);
}
