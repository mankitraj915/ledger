/** Typed client for the Ledger REST API. */

export interface User {
  id: number;
  email: string;
  name: string;
}

export interface Session {
  access_token: string;
  user: User;
}

export interface GroupSummary {
  id: number;
  name: string;
  currency: string;
  member_count: number;
  my_balance_cents: number;
}

export interface Member {
  user_id: number;
  name: string;
  email: string;
  balance_cents: number;
}

export interface Transfer {
  from_user_id: number;
  to_user_id: number;
  amount_cents: number;
}

export interface GroupDetail {
  id: number;
  name: string;
  currency: string;
  created_by: number;
  members: Member[];
  suggested_settlements: Transfer[];
}

export interface Split {
  user_id: number;
  share_cents: number;
  weight: number | null;
}

export interface Expense {
  id: number;
  description: string;
  amount_cents: number;
  paid_by: number;
  split_method: string;
  version: number;
  created_at: string;
  splits: Split[];
}

export interface Settlement {
  id: number;
  payer_id: number;
  payee_id: number;
  amount_cents: number;
  created_at: string;
}

export interface NewExpense {
  description: string;
  amount_cents: number;
  paid_by: number;
  split: { method: "equal"; participants: number[] };
}

export interface NewSettlement {
  payer_id: number;
  payee_id: number;
  amount_cents: number;
}

/** Mirrors the server's error envelope: {"error": {"code", "message", "details"}}. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type Unauthorised = () => void;

export class ApiClient {
  private readonly token: string | null;
  private readonly onUnauthorised: Unauthorised;

  constructor(token: string | null, onUnauthorised: Unauthorised = () => {}) {
    this.token = token;
    this.onUnauthorised = onUnauthorised;
  }

  register(email: string, name: string, password: string): Promise<Session> {
    return this.request("POST", "/auth/register", { email, name, password });
  }

  login(email: string, password: string): Promise<Session> {
    return this.request("POST", "/auth/login", { email, password });
  }

  listGroups(): Promise<GroupSummary[]> {
    return this.request("GET", "/groups");
  }

  createGroup(name: string, currency: string): Promise<{ id: number }> {
    return this.request("POST", "/groups", { name, currency });
  }

  getGroup(groupId: number): Promise<GroupDetail> {
    return this.request("GET", `/groups/${groupId}`);
  }

  addMember(groupId: number, email: string): Promise<Member> {
    return this.request("POST", `/groups/${groupId}/members`, { email });
  }

  listExpenses(groupId: number): Promise<Expense[]> {
    return this.request("GET", `/groups/${groupId}/expenses`);
  }

  addExpense(groupId: number, expense: NewExpense): Promise<Expense> {
    return this.request("POST", `/groups/${groupId}/expenses`, expense);
  }

  listSettlements(groupId: number): Promise<Settlement[]> {
    return this.request("GET", `/groups/${groupId}/settlements`);
  }

  /** The caller supplies the key and must reuse it when retrying the same attempt. */
  settle(groupId: number, settlement: NewSettlement, idempotencyKey: string): Promise<Settlement> {
    return this.request("POST", `/groups/${groupId}/settlements`, settlement, {
      "Idempotency-Key": idempotencyKey,
    });
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    extraHeaders: Record<string, string> = {},
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json", ...extraHeaders };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (this.token) headers.Authorization = `Bearer ${this.token}`;

    let response: Response;
    try {
      response = await fetch(`/api${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new ApiError(0, "network_error", "Could not reach the server. Please try again.");
    }

    if (response.status === 204) return undefined as T;
    const payload: unknown = await response.json().catch(() => null);
    if (response.ok) return payload as T;

    if (response.status === 401 && this.token) this.onUnauthorised();
    const error = (payload as { error?: { code?: string; message?: string; details?: unknown } })
      ?.error;
    throw new ApiError(
      response.status,
      error?.code ?? "http_error",
      error?.message ?? `Request failed (${response.status})`,
      error?.details,
    );
  }
}
