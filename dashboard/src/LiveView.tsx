import { useEffect } from "react";
import type { Run, RunClaim } from "./api";
import { cost, duration, money } from "./format";
import { leaveLiveView, useCountUp, useJson } from "./hooks";
import type { LiveOutcome } from "./live";
import { board, LIVE_OUTCOMES, outcomeOf, tally } from "./live";
import { SummaryOfRun } from "./RunPanel";
import { LoadingState } from "./ui";

const OUTCOMES = Object.keys(LIVE_OUTCOMES) as LiveOutcome[];

/** The live view: the latest dispatch as a board, one card for each claim. */
export function LiveView() {
  const { data: run } = useJson<Run | null>("/api/runs/current", 1000);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") leaveLiveView();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  return (
    <div className="live">
      <LiveTop run={run ?? null} />
      <div className="live-stage board-stage">
        {run && run.status !== "running" && <LiveSummary run={run} />}
        {run && <Board run={run} />}
        {run === null && <LiveIdle />}
        {run === undefined && <LoadingState what="the latest dispatch" />}
      </div>
    </div>
  );
}

function LiveTop({ run }: Readonly<{ run: Run | null }>) {
  const numbers = run ? tally(run) : null;
  const total = run?.total ?? 0;
  const done = numbers?.done ?? 0;
  const share = total === 0 ? 0 : (done / total) * 100;
  return (
    <header className="live-top">
      <span className="brand">UnderCover</span>
      <span className="live-position mono">
        {run
          ? `${String(done)} of ${String(total)} done · ${String(numbers?.working ?? 0)} at work`
          : ""}
      </span>
      <div
        className="live-progress"
        role="progressbar"
        aria-label="Claims done"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
      >
        <div
          className="live-progress-fill"
          style={{ width: `${String(share)}%` }}
        />
      </div>
      <ul className="live-tally" aria-label="Outcomes so far">
        {OUTCOMES.map((outcome) => (
          <li key={outcome} className={`chip chip-${outcome}`}>
            <span className="mono">{numbers?.counts[outcome] ?? 0}</span>{" "}
            {LIVE_OUTCOMES[outcome]}
          </li>
        ))}
      </ul>
      {run && (
        <span className="live-figures mono" aria-label="Cost and time">
          {cost(run.cost)} · {duration(run.elapsed)}
        </span>
      )}
      <button type="button" className="quiet" onClick={leaveLiveView}>
        Leave (Esc)
      </button>
    </header>
  );
}

function Board({ run }: Readonly<{ run: Run }>) {
  return (
    <ol className="board" aria-label={`Dispatch ${String(run.run_id)}`}>
      {board(run).map((claim) => (
        <BoardCard key={claim.claim_id} claim={claim} />
      ))}
    </ol>
  );
}

function BoardCard({ claim }: Readonly<{ claim: RunClaim }>) {
  const outcome = outcomeOf(claim);
  const working = claim.status === "in_progress";
  return (
    <li>
      <article
        className={`board-card panel${working ? " working" : ""}${claim.status === "waiting" ? " idle" : ""}`}
        aria-label={`Claim ${claim.claim_id}`}
      >
        <header className="board-card-head">
          <a className="mono" href={`#/claims/${claim.claim_id}`}>
            {claim.claim_id}
          </a>
          {working && <span className="pulse small" aria-hidden="true" />}
        </header>
        {outcome ? (
          <Stamp outcome={outcome} payout={claim.payout ?? 0} />
        ) : (
          <p className="board-step">
            {working
              ? (claim.latest_step ?? "Starting")
              : "Waiting for a claim agent"}
          </p>
        )}
        <footer className="board-card-foot mono">
          {cost(claim.cost)} · {duration(claim.seconds)}
        </footer>
      </article>
    </li>
  );
}

function Stamp({
  outcome,
  payout,
}: Readonly<{ outcome: LiveOutcome; payout: number }>) {
  const shown = useCountUp(payout);
  const pays = outcome === "approve" || outcome === "sign_off";
  return (
    <div className={`board-stamp stamp-${outcome}`} role="status">
      <div className="stamp">
        <span className="stamp-word">{LIVE_OUTCOMES[outcome]}</span>
        {pays && <span className="stamp-amount mono">{money(shown)}</span>}
      </div>
    </div>
  );
}

function LiveSummary({ run }: Readonly<{ run: Run }>) {
  const { counts, done, paid, awaiting } = tally(run);
  return (
    <section className="live-summary panel" aria-labelledby="summary-heading">
      <h1 id="summary-heading">
        {run.status === "finished"
          ? "The dispatch is done"
          : "The dispatch stopped partway"}
      </h1>
      <p className="tagline">
        {done} of {run.total} claims worked by {run.n} claim agents at once
      </p>
      <ul className="summary-counts">
        {OUTCOMES.map((outcome) => (
          <li key={outcome} className={`summary-count chip-${outcome}`}>
            <span className="summary-number mono">{counts[outcome]}</span>
            {LIVE_OUTCOMES[outcome]}
          </li>
        ))}
      </ul>
      <p className="summary-money">
        Payouts approved: <span className="mono">{money(paid)}</span>, and{" "}
        <span className="mono">{money(awaiting)}</span> waiting for sign-off
      </p>
      {run.summary && <SummaryOfRun summary={run.summary} />}
      <a href="#/" onClick={leaveLiveView}>
        Back to the queue
      </a>
    </section>
  );
}

function LiveIdle() {
  return (
    <section className="live-idle">
      <div className="pulse" aria-hidden="true" />
      <p>No dispatch yet. Start one on the queue page.</p>
    </section>
  );
}
