import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "../auth";

export function Layout({ children }: { children: ReactNode }) {
  const { user, signOut } = useAuth();
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">
          Ledger
        </Link>
        {user && (
          <div className="topbar-user">
            <span>{user.name}</span>
            <button type="button" className="link-button" onClick={signOut}>
              Sign out
            </button>
          </div>
        )}
      </header>
      <main className="page">{children}</main>
    </>
  );
}

export function ErrorText({ error }: { error: string | null }) {
  return error ? (
    <p className="error" role="alert">
      {error}
    </p>
  ) : null;
}

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong";
}
