import { useState } from "react";
import type { ClaimSummary, Run, Status } from "./api";
import { date, label, money, STATUS_LABELS } from "./format";
import { agentsAtOnce, DEFAULT_AGENTS, startDispatch, useJson } from "./hooks";
import { RunPanel } from "./RunPanel";
import { StatusBadge } from "./StatusBadge";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "./ui";

const STATUSES = Object.keys(STATUS_LABELS) as Status[];

export function Queue() {
  const {
    data: claims,
    error,
    reload,
  } = useJson<ClaimSummary[]>("/api/claims", 3000);
  const { data: run } = useJson<Run | null>("/api/runs/current", 1500);
  const { data: running } = useJson<Run | null>("/api/runs/running", 1500);
  const [agents, setAgents] = useState(DEFAULT_AGENTS);
  const [refusal, setRefusal] = useState<string | null>(null);

  if (error) return <ErrorState onRetry={reload} />;
  if (!claims) return <LoadingState what="the queue" />;

  const busy = Boolean(running);
  const start = () => {
    setRefusal(null);
    void startDispatch(agents).then(setRefusal);
  };

  return (
    <section aria-labelledby="queue-heading">
      <PageHeader
        title="The claims queue"
        id="queue-heading"
        actions={
          <>
            <a href="#/live">Watch live</a>
            <AgentsAtOnce value={agents} onChange={setAgents} />
            <button type="button" onClick={start} disabled={busy}>
              Start a dispatch
            </button>
          </>
        }
      >
        Every claim and where it stands. A dispatch works the claims waiting and
        in progress, oldest first, with up to 25 claim agents at once.
      </PageHeader>
      {busy && <p role="status">A dispatch or evaluation is already running</p>}
      {refusal && <p role="alert">{refusal}</p>}
      <RunPanel run={run} />
      <ul className="tiles">
        {STATUSES.map((status) => (
          <li key={status} className="panel tile">
            <span className="tile-count mono">
              {claims.filter((claim) => claim.status === status).length}
            </span>
            <StatusBadge status={status} />
          </li>
        ))}
      </ul>
      {claims.length === 0 && (
        <EmptyState title="The queue is empty.">
          New claims appear here as customers submit them.
        </EmptyState>
      )}
      <div className="panel table-panel">
        <table>
          <thead>
            <tr>
              <th scope="col">Claim</th>
              <th scope="col">Customer</th>
              <th scope="col">Type</th>
              <th scope="col">Summary</th>
              <th scope="col" className="number">
                Claimed
              </th>
              <th scope="col">Submitted</th>
              <th scope="col">Status</th>
              <th scope="col" className="number">
                Payout
              </th>
            </tr>
          </thead>
          <tbody>
            {claims.map((claim) => (
              <tr key={claim.claim_id}>
                <td className="mono">
                  <a href={`#/claims/${claim.claim_id}`}>{claim.claim_id}</a>
                </td>
                <td>{claim.customer_name}</td>
                <td>{label(claim.claim_type)}</td>
                <td className="summary">{claim.summary}</td>
                <td className="mono number">{money(claim.amount_claimed)}</td>
                <td className="mono">{date(claim.submitted_on)}</td>
                <td>
                  <StatusBadge status={claim.status} />
                </td>
                <td className="mono number">
                  {claim.payout === null ? "" : money(claim.payout)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** How many claim agents work at once: 1 to 25. */
export function AgentsAtOnce({
  value,
  onChange,
}: Readonly<{ value: number; onChange: (value: number) => void }>) {
  return (
    <label className="cap">
      Claim agents at once
      <input
        type="number"
        min={1}
        max={25}
        value={value}
        onChange={(event) => {
          onChange(agentsAtOnce(Number(event.target.value)));
        }}
      />
    </label>
  );
}
