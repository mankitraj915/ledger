import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

import { AlertIcon, CheckCircleIcon, CloseIcon } from "./icons";
import { Button } from "./ui";

type Kind = "success" | "error";

interface Toast {
  id: number;
  kind: Kind;
  message: string;
}

interface ToastApi {
  success: (message: string) => void;
  error: (message: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const DURATION_MS: Record<Kind, number> = { success: 4000, error: 7000 };
const MAX_VISIBLE = 3;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (kind: Kind, message: string) => {
      const id = nextId.current++;
      setToasts((current) => [...current, { id, kind, message }].slice(-MAX_VISIBLE));
      window.setTimeout(() => dismiss(id), DURATION_MS[kind]);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({ success: (m) => push("success", m), error: (m) => push("error", m) }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      {/* Two live regions: failures interrupt, confirmations wait their turn. */}
      <div className="toasts">
        <div role="status" aria-live="polite" className="toasts-group">
          {toasts.filter((t) => t.kind === "success").map((t) => (
            <ToastView key={t.id} toast={t} onDismiss={dismiss} />
          ))}
        </div>
        <div role="alert" aria-live="assertive" className="toasts-group">
          {toasts.filter((t) => t.kind === "error").map((t) => (
            <ToastView key={t.id} toast={t} onDismiss={dismiss} />
          ))}
        </div>
      </div>
    </ToastContext.Provider>
  );
}

function ToastView({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  const Icon = toast.kind === "success" ? CheckCircleIcon : AlertIcon;
  return (
    <div className={`toast toast-${toast.kind}`}>
      <Icon className="toast-icon" />
      <p className="toast-text">{toast.message}</p>
      <Button variant="ghost" size="sm" onClick={() => onDismiss(toast.id)} aria-label="Dismiss">
        <CloseIcon size={14} />
      </Button>
    </div>
  );
}

export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (!api) throw new Error("useToast must be used inside <ToastProvider>");
  return api;
}
