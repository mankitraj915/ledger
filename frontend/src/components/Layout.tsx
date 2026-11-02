import { useEffect, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api";
import { useAuth } from "../auth";
import { BrandMark } from "./icons";
import { Button, Monogram } from "./ui";

export function Layout({ children, narrow = false }: { children: ReactNode; narrow?: boolean }) {
  const { user, signOut } = useAuth();
  return (
    <>
      <a href="#main" className="visually-hidden skip-link">
        Skip to content
      </a>
      <header className="topbar">
        <div className={narrow ? "topbar-inner is-narrow" : "topbar-inner"}>
          <Link to="/" className="brand" aria-label="Ledger, all groups">
            <BrandMark />
            <span aria-hidden="true">Ledger</span>
          </Link>
          {user && (
            <div className="topbar-user">
              <Monogram name={user.name} />
              <span className="topbar-name">{user.name}</span>
              <Button variant="ghost" size="sm" onClick={signOut}>
                Sign out
              </Button>
            </div>
          )}
        </div>
      </header>
      <main id="main" className={narrow ? "page page-narrow" : "page"}>
        {children}
      </main>
    </>
  );
}

/** Sets the tab title so history and screen readers name the page. */
export function useTitle(title: string | null) {
  useEffect(() => {
    document.title = title ? `${title} · Ledger` : "Ledger";
  }, [title]);
}

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong";
}

export function statusOf(error: unknown): number | null {
  return error instanceof ApiError ? error.status : null;
}
