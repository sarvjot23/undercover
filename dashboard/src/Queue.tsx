import type { ClaimSummary, Status } from "./api";
import { postJson } from "./api";
import { date, label, money, STATUS_LABELS } from "./format";
import { enterFullscreen, useJson } from "./hooks";
import { StatusBadge } from "./StatusBadge";

const STATUSES = Object.keys(STATUS_LABELS) as Status[];

function runQueue() {
  enterFullscreen();
  postJson("/api/queue/run")
    .catch(() => undefined)
    .finally(() => {
      window.location.hash = "#/live";
    });
}

export function Queue() {
  const { data: claims, error } = useJson<ClaimSummary[]>("/api/claims", 3000);

  if (error) return <p role="alert">The backend is not responding.</p>;
  if (!claims) return <p>Loading the queue</p>;

  return (
    <section aria-labelledby="queue-heading">
      <div className="queue-head">
        <h2 id="queue-heading">The claims queue</h2>
        <a href="#/live">Watch live</a>
        <button
          type="button"
          onClick={runQueue}
          disabled={!claims.some((claim) => claim.status === "waiting")}
        >
          Run the queue
        </button>
      </div>
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
