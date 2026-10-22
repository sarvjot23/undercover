import { useEffect, useReducer } from "react";
import type { Claim, ClaimSummary, Decision, Step } from "./api";
import { getJson, postJson } from "./api";
import { label, money } from "./format";
import { enterFullscreen, leaveLiveView, useCountUp, useJson } from "./hooks";
import type { LiveOutcome, LiveState } from "./live";
import {
  HOLD_MS,
  LEAVE_MS,
  LIVE_OUTCOMES,
  outcomeOf,
  progress,
  reduce,
  START,
  tally,
} from "./live";

const OUTCOMES = Object.keys(LIVE_OUTCOMES) as LiveOutcome[];

export function LiveView() {
  const [state, dispatch] = useReducer(reduce, START);

  useEffect(() => {
    let live = true;
    const poll = () => {
      Promise.all([
        getJson<ClaimSummary[]>("/api/claims"),
        getJson<{ running: boolean }>("/api/queue/run"),
      ]).then(
        ([claims, run]) => {
          if (live) dispatch({ type: "poll", claims, running: run.running });
        },
        () => undefined,
      );
    };
    poll();
    const timer = setInterval(poll, 1000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (state.stage === "stamped" && !state.held) {
      const timer = setTimeout(() => {
        dispatch({ type: "held" });
      }, HOLD_MS);
      return () => {
        clearTimeout(timer);
      };
    }
    if (state.stage === "leaving") {
      const timer = setTimeout(() => {
        dispatch({ type: "left" });
      }, LEAVE_MS);
      return () => {
        clearTimeout(timer);
      };
    }
  }, [state.stage, state.held]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") leaveLiveView();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  const focus = state.claims.find((claim) => claim.claim_id === state.focus);

  return (
    <div className="live">
      <LiveTop state={state} />
      <div className="live-stage">
        {focus && (
          <LiveCard key={focus.claim_id} summary={focus} stage={state.stage} />
        )}
        {!focus && state.finished.length > 0 && !state.running && (
          <LiveSummary state={state} />
        )}
        {!focus && (state.finished.length === 0 || state.running) && (
          <LiveIdle state={state} />
        )}
      </div>
    </div>
  );
}

function LiveTop({ state }: Readonly<{ state: LiveState }>) {
  const { position, total } = progress(state);
  const { counts } = tally(state);
  const share = total === 0 ? 0 : (state.finished.length / total) * 100;
  return (
    <header className="live-top">
      <span className="brand">UnderCover</span>
      <span className="live-position mono">
        {position > 0 ? `Claim ${String(position)} of ${String(total)}` : ""}
      </span>
      <div
        className="live-progress"
        role="progressbar"
        aria-label="Claims decided"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={state.finished.length}
      >
        <div
          className="live-progress-fill"
          style={{ width: `${String(share)}%` }}
        />
      </div>
      <ul className="live-tally" aria-label="Outcomes so far">
        {OUTCOMES.map((outcome) => (
          <li key={outcome} className={`chip chip-${outcome}`}>
            <span className="mono">{counts[outcome]}</span>{" "}
            {LIVE_OUTCOMES[outcome]}
          </li>
        ))}
      </ul>
      <button type="button" className="quiet" onClick={leaveLiveView}>
        Leave (Esc)
      </button>
    </header>
  );
}

function pollWorking(claim: Claim): number {
  return claim.agent_working ? 1000 : 0;
}

function LiveCard({
  summary,
  stage,
}: Readonly<{ summary: ClaimSummary; stage: LiveState["stage"] }>) {
  const { data: claim } = useJson<Claim>(
    `/api/claims/${summary.claim_id}`,
    pollWorking,
  );
  const outcome = stage === "working" ? null : outcomeOf(summary);

  return (
    <article
      className={`live-card${stage === "leaving" ? " leaving" : ""}`}
      aria-label={`Claim ${summary.claim_id}`}
    >
      <div className="live-claim panel">
        <p className="live-id mono">{summary.claim_id}</p>
        <h1>{summary.summary}</h1>
        <p className="live-meta">
          {summary.customer_name} · {label(summary.claim_type)} ·{" "}
          <span className="mono">{money(summary.amount_claimed)}</span> claimed
        </p>
        {claim && <LiveClaimDetails claim={claim} />}
        {outcome && (
          <Stamp
            outcome={outcome}
            payout={summary.payout ?? 0}
            decision={claim?.decision ?? null}
          />
        )}
      </div>
      <LiveSteps
        claimId={summary.claim_id}
        working={claim?.agent_working !== false}
      />
    </article>
  );
}

function LiveClaimDetails({ claim }: Readonly<{ claim: Claim }>) {
  return (
    <>
      <p className="live-meta">{claim.plan.name}</p>
      <p className="live-story">{claim.story}</p>
      <ul className="live-items">
        {claim.items.map((item) => (
          <li key={item.description}>
            <span>{item.description}</span>
            <span className="mono">{money(item.amount)}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

function LiveSteps({
  claimId,
  working,
}: Readonly<{ claimId: string; working: boolean }>) {
  const steps = useJson<Step[]>(
    `/api/claims/${claimId}/steps`,
    working ? 800 : 0,
  );
  return (
    <div className="live-steps panel">
      <h2>The agent at work</h2>
      <ol className="steps">
        {(steps.data ?? []).slice(-8).map((step) => (
          <li key={step.step_id} className={`step step-${step.kind}`}>
            <span className="step-text">{step.text}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Stamp({
  outcome,
  payout,
  decision,
}: Readonly<{
  outcome: LiveOutcome;
  payout: number;
  decision: Decision | null;
}>) {
  const shown = useCountUp(payout);
  const pays = outcome === "approve" || outcome === "sign_off";
  return (
    <div className={`stamp-wrap stamp-${outcome}`} role="status">
      <div className="stamp">
        <span className="stamp-word">{LIVE_OUTCOMES[outcome]}</span>
        {pays && <span className="stamp-amount mono">{money(shown)}</span>}
      </div>
      {decision && (
        <>
          <p className="stamp-reasons">{decision.reasons}</p>
          <p className="stamp-section">{decision.policy_section}</p>
        </>
      )}
    </div>
  );
}

function LiveSummary({ state }: Readonly<{ state: LiveState }>) {
  const { counts, paid, awaiting } = tally(state);
  return (
    <section className="live-summary panel" aria-labelledby="summary-heading">
      <h1 id="summary-heading">The queue is done</h1>
      <p className="tagline">
        {state.finished.length} claims decided by the UnderCover Agent
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
      <a href="#/" onClick={leaveLiveView}>
        Back to the queue
      </a>
    </section>
  );
}

function LiveIdle({ state }: Readonly<{ state: LiveState }>) {
  const waiting = state.claims.some((claim) => claim.status === "waiting");
  const start = () => {
    enterFullscreen();
    postJson("/api/queue/run").catch(() => undefined);
  };
  return (
    <section className="live-idle">
      <div className="pulse" aria-hidden="true" />
      <p>
        {state.running
          ? "The agent is picking up the next claim"
          : "Waiting for the agent to pick up a claim"}
      </p>
      {!state.running && waiting && (
        <button type="button" onClick={start}>
          Run the queue
        </button>
      )}
    </section>
  );
}
