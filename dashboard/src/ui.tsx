// The pieces every page shares: its header, its states and its badges.
import type { ReactNode } from "react";

/** A page's title, a line on what the page is for, and its actions. */
export function PageHeader({
  title,
  id,
  children,
  actions,
}: Readonly<{
  title: ReactNode;
  id: string;
  children: ReactNode;
  actions?: ReactNode;
}>) {
  return (
    <header className="page-header">
      <div className="page-header-text">
        <h2 id={id}>{title}</h2>
        <p className="muted">{children}</p>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

/** Space kept for what's loading, so nothing jumps when it arrives. */
export function LoadingState({ what }: Readonly<{ what: string }>) {
  return (
    <p className="state state-loading" role="status">
      Loading {what}
    </p>
  );
}

/** Nothing to show yet, and what would fill it. */
export function EmptyState({
  title,
  children,
}: Readonly<{ title: string; children: ReactNode }>) {
  return (
    <div className="state state-empty">
      <p className="state-title">{title}</p>
      <p className="muted">{children}</p>
    </div>
  );
}

/** Something went wrong, and what to do next. */
export function ErrorState({
  message = "The backend is not responding.",
  children = "Check that UnderCover is running, then try again.",
  onRetry,
}: Readonly<{
  message?: string;
  children?: ReactNode;
  onRetry?: () => void;
}>) {
  return (
    <div className="state state-error">
      <p role="alert" className="state-title">
        {message}
      </p>
      <p className="muted">{children}</p>
      {onRetry && (
        <button type="button" className="secondary" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

export type Tone = "gold" | "champagne" | "antique" | "steel" | "burnished";

/** A status: a word on a color, never the color alone. */
export function Badge({
  tone,
  children,
}: Readonly<{ tone: Tone; children: ReactNode }>) {
  return <span className={`badge tone-${tone}`}>{children}</span>;
}
