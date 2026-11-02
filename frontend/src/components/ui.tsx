/** Hand-built primitives. Every visual decision lives in styles.css tokens. */

import { useId, type ButtonHTMLAttributes, type CSSProperties, type ReactNode } from "react";

import { formatCents } from "../money";
import { balanceLabel, initials, toneOf } from "../present";
import { CheckIcon, ChevronDownIcon, Spinner } from "./icons";

/* ---------------------------------------------------------------- Button */

type Variant = "primary" | "secondary" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "md" | "sm";
  block?: boolean;
  loading?: boolean;
}

export function Button({
  variant = "secondary",
  size = "md",
  block = false,
  loading = false,
  className,
  children,
  disabled,
  type = "button",
  ...rest
}: ButtonProps) {
  const classes = [
    "btn",
    `btn-${variant}`,
    size === "sm" && "btn-sm",
    block && "btn-block",
    loading && "is-loading",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button
      type={type}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      <span className="btn-label">{children}</span>
      {loading && <Spinner />}
    </button>
  );
}

/* ---------------------------------------------------------------- Field */

export interface ControlProps {
  id: string;
  "aria-invalid": boolean | undefined;
  "aria-describedby": string;
  className: string;
}

interface FieldProps {
  label: string;
  /** Shown in the reserved message line until an error replaces it. */
  hint?: string;
  error?: string;
  hideLabel?: boolean;
  children: (control: ControlProps) => ReactNode;
}

/** Label, control and a message line that is always present so errors never shift layout. */
export function Field({ label, hint, error, hideLabel = false, children }: FieldProps) {
  const id = useId();
  const messageId = `${id}-msg`;
  return (
    <div className="field">
      <label htmlFor={id} className={hideLabel ? "visually-hidden" : "field-label"}>
        {label}
      </label>
      {children({
        id,
        "aria-invalid": error ? true : undefined,
        "aria-describedby": messageId,
        className: "control",
      })}
      <p id={messageId} className={error ? "field-msg is-error" : "field-msg"}>
        {error ?? hint ?? ""}
      </p>
    </div>
  );
}

/** A native select wearing the same control treatment, with an SVG chevron. */
export function Select({
  control,
  value,
  onChange,
  options,
}: {
  control: ControlProps;
  value: string | number;
  onChange: (value: string) => void;
  options: { value: string | number; label: string }[];
}) {
  return (
    <span className="control-wrap">
      <select {...control} value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDownIcon className="select-chevron" />
    </span>
  );
}

/** Amount input with the currency symbol inside the border, figures tabular. */
export function AmountInput({
  control,
  symbol,
  value,
  onChange,
  autoFocus,
}: {
  control: ControlProps;
  symbol: string;
  value: string;
  onChange: (value: string) => void;
  autoFocus?: boolean;
}) {
  return (
    <span className="control-wrap has-prefix" style={{ "--prefix-width": `${symbol.length}ch` } as CSSProperties}>
      <span className="control-prefix num">{symbol}</span>
      <input
        {...control}
        className={`${control.className} num`}
        inputMode="decimal"
        autoComplete="off"
        placeholder="0.00"
        value={value}
        autoFocus={autoFocus}
        onChange={(e) => onChange(e.target.value)}
      />
    </span>
  );
}

/* ---------------------------------------------------------------- Segmented control */

/** Radio inputs underneath: arrow keys, labels and form semantics come for free. */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  const name = useId();
  return (
    <fieldset className="segmented">
      <legend className="visually-hidden">{label}</legend>
      {options.map((o) => (
        <label key={o.value}>
          <input
            type="radio"
            name={name}
            value={o.value}
            checked={value === o.value}
            onChange={() => onChange(o.value)}
          />
          <span>{o.label}</span>
        </label>
      ))}
    </fieldset>
  );
}

/* ---------------------------------------------------------------- Money */

export function Money({ cents, currency, className }: { cents: number; currency: string; className?: string }) {
  return <span className={className ? `num ${className}` : "num"}>{formatCents(cents, currency)}</span>;
}

/** A balance as a label over a right-aligned figure: meaning in words and colour. */
export function BalanceFigure({
  cents,
  currency,
  isViewer = false,
}: {
  cents: number;
  currency: string;
  isViewer?: boolean;
}) {
  const tone = toneOf(cents);
  if (tone === "settled") {
    return (
      <span className="figure-settled">
        <CheckIcon size={14} />
        Settled up
      </span>
    );
  }
  return (
    <span className={`figure tone-${tone}`}>
      <span className="figure-label">{balanceLabel(cents, isViewer)}</span>
      <Money cents={Math.abs(cents)} currency={currency} className="figure-value" />
    </span>
  );
}

export function Monogram({ name, square = false }: { name: string; square?: boolean }) {
  return (
    <span className={square ? "monogram monogram-square" : "monogram"} aria-hidden="true">
      {initials(name) || "?"}
    </span>
  );
}

/* ---------------------------------------------------------------- States */

export function Skeleton({ width, height, className }: { width?: string; height?: string; className?: string }) {
  return (
    <span
      className={className ? `skeleton ${className}` : "skeleton"}
      style={{ width, height }}
      aria-hidden="true"
    />
  );
}

/** Placeholder rows shaped like the real ledger rows, so nothing jumps when data lands. */
export function SkeletonRows({ count = 3, withDate = false }: { count?: number; withDate?: boolean }) {
  return (
    <ul className="rows" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <li key={i} className="row">
          {withDate ? <Skeleton className="date-col" width="32px" /> : <Skeleton className="skeleton-circle" />}
          <span>
            <Skeleton width={`${40 + ((i * 17) % 30)}%`} />
            <Skeleton width="22%" height="0.65em" className="skeleton-sub" />
          </span>
          <Skeleton width="64px" />
        </li>
      ))}
    </ul>
  );
}

export function EmptyState({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <p className="empty-text">{children}</p>
      {action}
    </div>
  );
}

export function Callout({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="callout" role="alert">
      <span>{children}</span>
      {action}
    </div>
  );
}
