import type { Run, RunSummary } from "./api";
import { cost, duration, money } from "./format";
import { hasEnded } from "./live";
import { StatusBadge } from "./StatusBadge";

const RUN_LABELS: Record<Run["status"], string> = {
  running: "Running",
  finished: "Finished",
  stopped: "Stopped partway",
};

/** The latest dispatch: its claims and where each stands, its cost and time, its summary. */
export function RunPanel({ run }: Readonly<{ run: Run | null | undefined }>) {
  if (!run) return null;
  const done = run.claims.filter((claim) => hasEnded(claim.status)).length;

  return (
    <section className="panel run-panel" aria-labelledby="run-heading">
      <div className="run-head">
        <h3 id="run-heading">The latest dispatch</h3>
        <span className="muted">
          {RUN_LABELS[run.status]} &middot;{" "}
          <span className="mono">{run.n}</span> claim agents at once &middot;{" "}
          <span className="mono">{done}</span> of{" "}
          <span className="mono">{run.total}</span> claims done
        </span>
      </div>
      <RunFigures run={run} />
      <ol className="run-claims" aria-label="The dispatch's claims">
        {run.claims.map((claim) => (
          <li key={claim.claim_id}>
            <a className="mono" href={`#/claims/${claim.claim_id}`}>
              {claim.claim_id}
            </a>
            <StatusBadge status={claim.status} />
          </li>
        ))}
      </ol>
      {run.summary && <SummaryOfRun summary={run.summary} />}
    </section>
  );
}

/** A run's model cost, the agents' time on its claims, and the run's own time. */
export function RunFigures({ run }: Readonly<{ run: Run }>) {
  return (
    <dl className="run-figures">
      <div>
        <dt>Model cost</dt>
        <dd className="mono">{cost(run.cost)}</dd>
      </div>
      <div>
        <dt>Agent time</dt>
        <dd className="mono">{duration(run.seconds)}</dd>
      </div>
      <div>
        <dt>Run time</dt>
        <dd className="mono">{duration(run.elapsed)}</dd>
      </div>
    </dl>
  );
}

/** The summary of an ended dispatch, from the records. */
export function SummaryOfRun({ summary }: Readonly<{ summary: RunSummary }>) {
  return (
    <div className="run-summary">
      <h4>Summary</h4>
      <p>
        <span className="mono">{summary.approved}</span> approved,{" "}
        <span className="mono">{summary.declined}</span> declined and{" "}
        <span className="mono">{summary.referred}</span> referred.
      </p>
      {summary.awaiting_sign_off.length > 0 && (
        <p>
          Waiting for a sign-off:{" "}
          {summary.awaiting_sign_off.map((held, index) => (
            <span key={held.claim_id}>
              {index > 0 && ", "}
              <a className="mono" href={`#/claims/${held.claim_id}`}>
                {held.claim_id}
              </a>{" "}
              <span className="mono">{money(held.payout)}</span>
            </span>
          ))}
        </p>
      )}
      <ClaimList
        label="Left for a handler"
        claimIds={summary.left_for_handler}
      />
      <ClaimList label="Still in progress" claimIds={summary.in_progress} />
    </div>
  );
}

function ClaimList({
  label,
  claimIds,
}: Readonly<{ label: string; claimIds: string[] }>) {
  if (claimIds.length === 0) return null;
  return (
    <p>
      {label}:{" "}
      {claimIds.map((claimId, index) => (
        <span key={claimId}>
          {index > 0 && ", "}
          <a className="mono" href={`#/claims/${claimId}`}>
            {claimId}
          </a>
        </span>
      ))}
    </p>
  );
}
