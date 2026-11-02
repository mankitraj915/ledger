import { useRef, useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import { useAuth } from "../auth";
import { BrandMark } from "../components/icons";
import { messageOf, statusOf, useTitle } from "../components/Layout";
import { useToast } from "../components/Toast";
import { Button, Field, Segmented } from "../components/ui";
import { hasErrors, MIN_PASSWORD_LENGTH, validateAuth, type AuthField, type Errors } from "../validation";

type Mode = "signin" | "register";

export function LoginPage() {
  const { api, user, signIn } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("signin");
  const [values, setValues] = useState({ email: "", name: "", password: "" });
  const [errors, setErrors] = useState<Errors<AuthField>>({});
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  useTitle(mode === "signin" ? "Sign in" : "Create account");

  if (user) return <Navigate to="/" replace />;

  function update(field: AuthField, value: string) {
    const next = { ...values, [field]: value };
    setValues(next);
    // After the first attempt, re-check as the user types so errors clear promptly.
    if (submitted) setErrors(validateAuth(mode, next));
  }

  function switchMode(next: Mode) {
    setMode(next);
    setErrors(submitted ? validateAuth(next, values) : {});
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitted(true);
    const found = validateAuth(mode, values);
    setErrors(found);
    if (hasErrors(found)) {
      formRef.current?.querySelector<HTMLElement>("[aria-invalid='true']")?.focus();
      return;
    }
    setBusy(true);
    try {
      const session =
        mode === "signin"
          ? await api.login(values.email.trim(), values.password)
          : await api.register(values.email.trim(), values.name.trim(), values.password);
      signIn(session);
      navigate("/");
    } catch (err) {
      // Put answers next to the field they are about; anything else is a toast.
      const status = statusOf(err);
      if (mode === "signin" && status === 401) setErrors({ password: messageOf(err) });
      else if (mode === "register" && status === 409) setErrors({ email: messageOf(err) });
      else toast.error(messageOf(err));
      setBusy(false);
    }
  }

  const passwordHint = mode === "register" ? `At least ${MIN_PASSWORD_LENGTH} characters` : undefined;

  return (
    <main className="auth">
      <div className="auth-inner">
        <header className="auth-brand">
          <BrandMark size={32} />
          <div>
            <h1 className="auth-title">Ledger</h1>
            <p className="auth-tagline">Shared expenses, settled to the cent.</p>
          </div>
        </header>

        <section className="panel auth-card" aria-label={mode === "signin" ? "Sign in" : "Create account"}>
          <Segmented
            label="Account"
            value={mode}
            onChange={switchMode}
            options={[
              { value: "signin", label: "Sign in" },
              { value: "register", label: "Create account" },
            ]}
          />
          <form ref={formRef} onSubmit={submit} className="form" noValidate>
            <Field label="Email" error={errors.email}>
              {(control) => (
                <input
                  {...control}
                  type="email"
                  autoComplete="email"
                  autoCapitalize="none"
                  spellCheck={false}
                  value={values.email}
                  onChange={(e) => update("email", e.target.value)}
                />
              )}
            </Field>
            {mode === "register" && (
              <Field label="Name" error={errors.name}>
                {(control) => (
                  <input
                    {...control}
                    autoComplete="name"
                    maxLength={100}
                    value={values.name}
                    onChange={(e) => update("name", e.target.value)}
                  />
                )}
              </Field>
            )}
            <Field label="Password" error={errors.password} hint={passwordHint}>
              {(control) => (
                <input
                  {...control}
                  type="password"
                  autoComplete={mode === "signin" ? "current-password" : "new-password"}
                  value={values.password}
                  onChange={(e) => update("password", e.target.value)}
                />
              )}
            </Field>
            <Button type="submit" variant="primary" block loading={busy}>
              {mode === "signin" ? "Sign in" : "Create account"}
            </Button>
          </form>
        </section>

        <p className="auth-footnote">
          Amounts are stored as whole cents and every group's balances always sum to zero.
        </p>
      </div>
    </main>
  );
}
