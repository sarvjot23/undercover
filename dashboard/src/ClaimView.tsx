import { useState } from "react";
import type { Claim, Handler, Step } from "./api";
import { postJson } from "./api";
import { date, label, money, OUTCOME_LABELS } from "./format";
import { useJson } from "./hooks";
import { StatusBadge } from "./StatusBadge";
import { Steps } from "./Steps";

/** Follow a claim while the agent may still pick it up or is working on it. */
function pollClaim(claim: Claim): number {
  return claim.status === "waiting" || claim.agent_working ? 1000 : 0;
}

export function ClaimView({ claimId }: Readonly<{ claimId: string }>) {
  const [starting, setStarting] = useState(false);
  const [problem, setProblem] = useState("");
  const path = `/api/claims/${claimId}`;
  const { data: claim, error, reload } = useJson<Claim>(path, pollClaim);
  const steps = useJson<Step[]>(
    `${path}/steps`,
    claim?.agent_working ? 1000 : 0,
  );

  if (error) return <p role="alert">There is no claim {claimId}.</p>;
  if (!claim) return <p>Loading the claim</p>;

  const run = () => {
    setStarting(true);
    postJson(`${path}/run`).then(reload, () => {
      setStarting(false);
      setProblem("The agent couldn't start on this claim.");
    });
  };

  return (
    <section aria-labelledby="claim-heading" className="claim">
      <a href="#/">Back to the queue</a>
      <div className="claim-head">
        <h2 id="claim-heading">
          <span className="mono">{claim.claim_id}</span> {claim.summary}
        </h2>
        <StatusBadge status={claim.status} />
        {claim.status === "waiting" && (
          <button type="button" onClick={run} disabled={starting}>
            Run the agent
          </button>
        )}
      </div>
      {problem && <p role="alert">{problem}</p>}
      <div className="claim-grid">
        <div className="claim-main">
          <ClaimStory claim={claim} />
          <div className="panel">
            <h3>The agent at work</h3>
            <Steps steps={steps.data ?? []} />
          </div>
        </div>
        <div className="claim-side">
          <DecisionPanel claim={claim} onSignedOff={reload} />
          <PolicyPanel claim={claim} />
        </div>
      </div>
    </section>
  );
}

function ClaimStory({ claim }: Readonly<{ claim: Claim }>) {
  return (
    <div className="panel">
      <h3>The claim</h3>
      <p className="muted">
        {label(claim.claim_type)} in {claim.incident_location} on{" "}
        <span className="mono">{date(claim.incident_date)}</span>, submitted{" "}
        <span className="mono">{date(claim.submitted_on)}</span>
      </p>
      <p className="story">{claim.story}</p>
      <table className="items">
        <tbody>
          {claim.items.map((item) => (
            <tr key={item.description}>
              <td>{item.description}</td>
              <td className="muted">{label(item.category)}</td>
              <td className="mono number">{money(item.amount)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row" colSpan={2}>
              Total claimed
            </th>
            <td className="mono number">{money(claim.amount_claimed)}</td>
          </tr>
        </tfoot>
      </table>
      <h4>Documents</h4>
      {claim.documents.map((document) => (
        <details key={document.name} className="document">
          <summary>{document.name}</summary>
          <p>{document.content}</p>
        </details>
      ))}
    </div>
  );
}

function DecisionPanel({
  claim,
  onSignedOff,
}: Readonly<{ claim: Claim; onSignedOff: () => void }>) {
  const { decision, payment } = claim;
  if (!decision) {
    return (
      <div className="panel">
        <h3>Decision</h3>
        <p className="muted">No decision yet.</p>
      </div>
    );
  }
  return (
    <div className="panel">
      <h3>Decision</h3>
      <p className={`outcome outcome-${decision.decision}`}>
        {OUTCOME_LABELS[decision.decision]}
        <span className="mono">{money(decision.payout)}</span>
      </p>
      <p>{decision.reasons}</p>
      <p className="muted">Policy: {decision.policy_section}</p>
      {payment && <PaymentLine claim={claim} />}
      {claim.status === "awaiting_sign_off" && (
        <SignOff claimId={claim.claim_id} onSignedOff={onSignedOff} />
      )}
    </div>
  );
}

function PaymentLine({ claim }: Readonly<{ claim: Claim }>) {
  const handlers = useJson<Handler[]>("/api/handlers");
  const payment = claim.payment;
  if (!payment) return null;
  const signer = handlers.data?.find(
    (handler) => handler.handler_id === payment.signed_off_by,
  );
  return (
    <p className="paid">
      Paid <span className="mono">{money(payment.amount)}</span> on{" "}
      <span className="mono">{date(payment.paid_at)}</span>
      {signer && `, signed off by ${signer.name}`}
    </p>
  );
}

function SignOff({
  claimId,
  onSignedOff,
}: Readonly<{ claimId: string; onSignedOff: () => void }>) {
  const handlers = useJson<Handler[]>("/api/handlers");
  const [handlerId, setHandlerId] = useState("");
  const [problem, setProblem] = useState("");
  const chosen =
    handlerId === "" ? (handlers.data?.[0]?.handler_id ?? "") : handlerId;

  const signOff = () => {
    postJson(`/api/claims/${claimId}/sign-off`, { handler_id: chosen }).then(
      onSignedOff,
      () => {
        setProblem("The sign-off didn't go through.");
      },
    );
  };

  return (
    <div className="sign-off">
      <p>
        This payout is over $800.00, so the payment waits for a handler&rsquo;s
        sign-off.
      </p>
      <label>
        Handler{" "}
        <select
          value={chosen}
          onChange={(event) => {
            setHandlerId(event.target.value);
          }}
        >
          {handlers.data?.map((handler) => (
            <option key={handler.handler_id} value={handler.handler_id}>
              {handler.name}
            </option>
          ))}
        </select>
      </label>
      <button type="button" onClick={signOff} disabled={!chosen}>
        Sign off
      </button>
      {problem && <p role="alert">{problem}</p>}
    </div>
  );
}

function PolicyPanel({ claim }: Readonly<{ claim: Claim }>) {
  const { policy, plan, customer } = claim;
  return (
    <div className="panel">
      <h3>Policy and customer</h3>
      <dl className="facts">
        <dt>Customer</dt>
        <dd>
          {customer.name}, since{" "}
          <span className="mono">{date(customer.customer_since)}</span>
        </dd>
        <dt>Policy</dt>
        <dd className="mono">{policy.policy_id}</dd>
        <dt>Plan</dt>
        <dd>{plan.name}</dd>
        <dt>Add-ons</dt>
        <dd>{policy.add_ons.map(label).join(", ") || "None"}</dd>
        <dt>Trip</dt>
        <dd>
          {policy.trip.destination},{" "}
          <span className="mono">
            {date(policy.trip.departs_on)} to {date(policy.trip.returns_on)}
          </span>
        </dd>
        <dt>Travelers</dt>
        <dd>{policy.travelers.join(", ")}</dd>
      </dl>
      <h4>Earlier claims</h4>
      {customer.previous_claims.length === 0 ? (
        <p className="muted">None.</p>
      ) : (
        <ul className="history">
          {customer.previous_claims.map((previous) => (
            <li key={previous.claim_id}>
              <span className="mono">{previous.claim_id}</span>{" "}
              {previous.summary}: {previous.outcome},{" "}
              <span className="mono">{money(previous.amount_paid)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
