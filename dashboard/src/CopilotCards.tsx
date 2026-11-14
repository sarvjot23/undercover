// The Copilot's cards: each step it takes, with an icon for its kind and how it went.
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import type { CopilotStep, StepKind } from "./conversations";
import { secondsBetween } from "./conversations";
import { duration } from "./format";

const SHOWN_LENGTH = 1200;

/** The seconds so far, ticking each second while something works. */
function useNow(ticking: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!ticking) return;
    const timer = setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => {
      clearInterval(timer);
    };
  }, [ticking]);
  return now;
}

const ICONS: Record<StepKind, ReactNode> = {
  claims: <path d="M6 3h9l3 3v15H6zM9 10h6M9 14h6M9 18h4" />,
  customers: (
    <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c1-4 4-6 8-6s7 2 8 6" />
  ),
  context: <path d="M4 5h7a2 2 0 0 1 2 2v13a2 2 0 0 0-2-2H4zM20 5h-7v15h7z" />,
  work: <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18" />,
  memory: <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2" />,
  action: <path d="M13 3 5 14h6l-1 7 8-11h-6z" />,
};

function KindIcon({ kind }: Readonly<{ kind: StepKind }>) {
  return (
    <svg
      className="copilot-icon"
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {ICONS[kind]}
    </svg>
  );
}

/** The Copilot's own icon, on its tab and in its header. */
export function CopilotIcon() {
  return (
    <svg
      className="copilot-icon"
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 3l1.8 4.6L18.5 9l-4.7 1.5L12 15l-1.8-4.5L5.5 9l4.7-1.4zM18 15l.9 2.1L21 18l-2.1.9L18 21l-.9-2.1L15 18l2.1-.9z" />
    </svg>
  );
}

function trimmed(text: string): string {
  return text.length > SHOWN_LENGTH ? `${text.slice(0, SHOWN_LENGTH)}…` : text;
}

function StepState({
  step,
  now,
}: Readonly<{ step: CopilotStep; now: number }>) {
  if (step.state === "working") {
    const seconds = secondsBetween(
      step.started_at,
      new Date(now).toISOString(),
    );
    return (
      <span className="card-state">
        <span className="spinner" aria-hidden="true" />
        Working {duration(seconds)}
      </span>
    );
  }
  if (step.state === "done") {
    return <span className="card-state">{duration(step.seconds)}</span>;
  }
  return (
    <span className="card-state card-problem">
      {step.state === "refused" ? "Refused" : "Failed"}
    </span>
  );
}

/** One step the Copilot took: its kind, the tool and its main input, and how it
 * went, opening to what was asked and what came back. */
export function StepCard({ step }: Readonly<{ step: CopilotStep }>) {
  const [open, setOpen] = useState(false);
  const now = useNow(step.state === "working");
  const problem = step.state === "refused" || step.state === "failed";
  return (
    <li className={`copilot-card kind-${step.kind} state-${step.state}`}>
      <button
        type="button"
        className="card-head"
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
        }}
      >
        <KindIcon kind={step.kind} />
        <span className="card-name mono">
          {step.input ? `${step.tool} ` : step.tool}
          {step.input && <span className="card-input">{step.input}</span>}
        </span>
        <StepState step={step} now={now} />
      </button>
      {problem && step.reason && <p className="card-reason">{step.reason}</p>}
      {open && (
        <div className="card-detail">
          <p className="card-label">Asked</p>
          <pre>{trimmed(step.asked)}</pre>
          <p className="card-label">Came back</p>
          <pre>{trimmed(step.answer) || "Nothing yet"}</pre>
          {step.sources.map((source) => (
            <p key={source.file} className="muted card-source">
              <span className="mono">{source.file}</span>, owned by{" "}
              {source.owner}
            </p>
          ))}
        </div>
      )}
    </li>
  );
}
