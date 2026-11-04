import { useState } from "react";
import type { Claim, Handler, Step } from "./api";
import { postForRefusal, postJson } from "./api";
import { date, dateTime, label, money, OUTCOME_LABELS } from "./format";
import { ONLY_APPROVERS, useHandler } from "./handler";
import { useJson } from "./hooks";
import { StatusBadge } from "./StatusBadge";
import { Steps } from "./Steps";

/** Where a claim stands; here, only whether it's an evaluation's copy. */
interface Standing {
  evaluation_id: number | null;
}

/** Follow a claim while the agent may still pick it up or is working on it. */
function pollClaim(claim: Claim): number {
  if (claim.sign_off && !claim.payment) return 300;
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
  const { data: standing } = useJson<Standing>(`${path}/standing`);
  const evaluationId = standing?.evaluation_id ?? null;

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
        {claim.attempts > 0 && (
          <span className="muted">
            <span className="mono">{claim.attempts}</span> failed{" "}
            {claim.attempts === 1 ? "attempt" : "attempts"}
          </span>
        )}
        {claim.status === "waiting" && evaluationId === null && (
          <button type="button" onClick={run} disabled={starting}>
            Run the agent
          </button>
        )}
      </div>
      {problem && <p role="alert">{problem}</p>}
      {evaluationId !== null && (
        <p className="muted">
          A copy for{" "}
          <a href={`#/scoreboard/${String(evaluationId)}`}>
            evaluation {evaluationId}
          </a>
          . Nobody signs off a copy: an approval held for sign-off counts as
          finished.
        </p>
      )}
      <div className="claim-grid">
        <div className="claim-main">
          <ClaimStory claim={claim} />
          <div className="panel">
            <h3>The agent at work</h3>
            <Steps steps={steps.data ?? []} />
          </div>
        </div>
        <div className="claim-side">
          <DecisionPanel
            claim={claim}
            isCopy={evaluationId !== null}
            onSignedOff={reload}
          />
          <Reads steps={steps.data ?? []} />
          <PolicyPanel claim={claim} />
        </div>
      </div>
    </section>
  );
}

/** The sections of the wording and the manual the agent opened, in order. */
function Reads({ steps }: Readonly<{ steps: Step[] }>) {
  const reads = steps.filter((step) => step.kind === "read");
  if (reads.length === 0) return null;
  return (
    <section className="panel" aria-labelledby="reads-heading">
      <h3 id="reads-heading">What the agent read</h3>
      <ol className="reads">
        {reads.map((step) => (
          <li key={step.step_id}>{step.text}</li>
        ))}
      </ol>
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
  isCopy,
  onSignedOff,
}: Readonly<{ claim: Claim; isCopy: boolean; onSignedOff: () => void }>) {
  const { decision, payment } = claim;
  const { data: handlers } = useJson<Handler[]>("/api/handlers");
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
      {payment ? (
        <PaymentLine claim={claim} handlers={handlers} />
      ) : (
        <SignedOff claim={claim} handlers={handlers} />
      )}
      {claim.status === "awaiting_sign_off" && !isCopy && (
        <SignOff
          claimId={claim.claim_id}
          limit={decision.approval_limit}
          onSignedOff={onSignedOff}
        />
      )}
    </div>
  );
}

/** A sign-off the agent hasn't paid yet: it's picking the claim back up. */
function SignedOff({
  claim,
  handlers,
}: Readonly<{ claim: Claim; handlers: Handler[] | undefined }>) {
  const signOff = claim.sign_off;
  if (!signOff) return null;
  const signer = handlers?.find(
    (handler) => handler.handler_id === signOff.handler_id,
  );
  return (
    <p className="muted">
      Signed off by {signer?.name} on{" "}
      <span className="mono">{dateTime(signOff.signed_off_at)}</span>. The agent
      is paying it.
    </p>
  );
}

function PaymentLine({
  claim,
  handlers,
}: Readonly<{ claim: Claim; handlers: Handler[] | undefined }>) {
  const payment = claim.payment;
  if (!payment) return null;
  const signer = handlers?.find(
    (handler) => handler.handler_id === payment.signed_off_by,
  );
  return (
    <p className="paid">
      Paid <span className="mono">{money(payment.amount)}</span> on{" "}
      <span className="mono">{dateTime(payment.paid_at)}</span>
      {signer && payment.signed_off_at && (
        <>
          , signed off by {signer.name} on{" "}
          <span className="mono">{dateTime(payment.signed_off_at)}</span>
        </>
      )}
    </p>
  );
}

function SignOff({
  claimId,
  limit,
  onSignedOff,
}: Readonly<{ claimId: string; limit: number; onSignedOff: () => void }>) {
  const handler = useHandler();
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const why = (
    <p>
      This payout is over the approval limit of {money(limit)}, so the payment
      waits for a handler&rsquo;s sign-off.
    </p>
  );

  if (!handler?.can_approve_over_limit) {
    return (
      <div className="sign-off">
        {why}
        <p className="muted">{ONLY_APPROVERS} can sign this off.</p>
      </div>
    );
  }

  const signOff = () => {
    setBusy(true);
    setProblem("");
    void postForRefusal(`/api/claims/${claimId}/sign-off`).then((refusal) => {
      setBusy(false);
      if (refusal) setProblem(refusal);
      else onSignedOff();
    });
  };

  return (
    <div className="sign-off">
      {why}
      <button type="button" onClick={signOff} disabled={busy}>
        Sign off as {handler.name}
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
