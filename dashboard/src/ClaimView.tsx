import { useState } from "react";
import type { Claim, Decision, Handler, SentBack, Step } from "./api";
import { postForRefusal, postJson } from "./api";
import { ContextUsed } from "./ContextUsed";
import { date, dateTime, label, money, OUTCOME_LABELS } from "./format";
import { ONLY_APPROVERS, useHandler } from "./handler";
import { useJson } from "./hooks";
import { StatusBadge } from "./StatusBadge";
import { Steps } from "./Steps";
import { ErrorState, LoadingState } from "./ui";

/** Where a claim stands; here, only whether it's an evaluation's copy. */
interface Standing {
  evaluation_id: number | null;
}

const NOTE_LENGTH = 1000;

/** Follow a claim while the agent may still pick it up or is working on it. */
function pollClaim(claim: Claim): number {
  const waiting = claim.status === "waiting" || claim.status === "sent_back";
  return waiting || claim.agent_working ? 1000 : 0;
}

/** Follow the steps while the agent works, and while a claim sent back waits for it:
 * the note is a step of its own. */
function followSteps(claim: Claim | undefined): number {
  return claim?.agent_working || claim?.status === "sent_back" ? 1000 : 0;
}

export function ClaimView({ claimId }: Readonly<{ claimId: string }>) {
  const [starting, setStarting] = useState(false);
  const [problem, setProblem] = useState("");
  const path = `/api/claims/${claimId}`;
  const { data: claim, error, reload } = useJson<Claim>(path, pollClaim);
  const steps = useJson<Step[]>(`${path}/steps`, followSteps(claim));
  const { data: standing } = useJson<Standing>(`${path}/standing`);
  const evaluationId = standing?.evaluation_id ?? null;

  if (error) {
    return (
      <ErrorState message={`There is no claim ${claimId}.`}>
        <a href="#/">Back to the queue</a> to choose another.
      </ErrorState>
    );
  }
  if (!claim) return <LoadingState what="the claim" />;

  const run = () => {
    setStarting(true);
    postJson(`${path}/run`).then(reload, () => {
      setStarting(false);
      setProblem("The agent couldn't start on this claim.");
    });
  };

  return (
    <section aria-labelledby="claim-heading" className="claim">
      <a className="back" href="#/">
        Back to the queue
      </a>
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
      <NextDispatch claim={claim} />
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
          <SentBackPanel key={claim.status} path={`${path}/sent-back`} />
          <ContextUsed steps={steps.data ?? []} />
          <PolicyPanel claim={claim} />
        </div>
      </div>
    </section>
  );
}

/** A sent-back claim the agent hasn't taken waits for the next dispatch. */
function NextDispatch({ claim }: Readonly<{ claim: Claim }>) {
  if (claim.status !== "sent_back" || claim.agent_working) return null;
  return (
    <p className="muted">
      Waiting for the next dispatch, which gives the claim back to the agent.
    </p>
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
      <dl className="facts">
        <dt>Section</dt>
        <dd>{decision.policy_section}</dd>
        <dt>Decided by</dt>
        <dd>{decision.decided_by}</dd>
        <dt>When</dt>
        <dd className="mono">{dateTime(decision.decided_at)}</dd>
        <dt>Claims manual</dt>
        <dd>
          Version <span className="mono">{decision.manual_version}</span>
        </dd>
      </dl>
      <Calculation decision={decision} />
      {payment && <PaymentLine claim={claim} handlers={handlers} />}
      {claim.status === "awaiting_sign_off" && !isCopy && (
        <SignOff
          claimId={claim.claim_id}
          decision={decision}
          onSignedOff={onSignedOff}
        />
      )}
    </div>
  );
}

/** The decisions a handler sent back to the agent, each with its note. */
function SentBackPanel({ path }: Readonly<{ path: string }>) {
  const { data: returned } = useJson<SentBack[]>(path);
  if (!returned || returned.length === 0) return null;
  return (
    <div className="panel">
      <h3>Sent back</h3>
      <ol className="sent-back">
        {returned.map((back) => (
          <li key={back.sent_back_id}>
            <p className="muted">
              {back.handler_name} sent back{" "}
              {OUTCOME_LABELS[back.decision.decision].toLowerCase()}{" "}
              <span className="mono">{money(back.decision.payout)}</span> on{" "}
              <span className="mono">{dateTime(back.sent_back_at)}</span>
            </p>
            <blockquote className="note">{back.note}</blockquote>
            <p className="muted">{back.decision.reasons}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** How an approval's payout was worked out, line by line. */
function Calculation({ decision }: Readonly<{ decision: Decision }>) {
  const { calculation } = decision;
  if (!calculation) return null;
  return (
    <table className="items calculation" aria-label="Calculation">
      <tbody>
        {calculation.lines.map((line, index) => (
          <tr key={`${String(index)}-${line.step}`}>
            <td>{line.step}</td>
            <td className="mono number">{money(line.amount)}</td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr>
          <th scope="row">Payout</th>
          <td className="mono number">{money(calculation.payout)}</td>
        </tr>
      </tfoot>
    </table>
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
  decision,
  onSignedOff,
}: Readonly<{
  claimId: string;
  decision: Decision;
  onSignedOff: () => void;
}>) {
  const handler = useHandler();
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const why = decision.payment_refused ? (
    <p>
      The Gateway refused the payment, so it waits for a handler&rsquo;s
      sign-off: {decision.payment_refused}
    </p>
  ) : (
    <p>
      This payout is over the approval limit of {money(decision.approval_limit)}
      , so the payment waits for a handler&rsquo;s sign-off.
    </p>
  );

  if (!handler?.can_approve_over_limit) {
    return (
      <div className="sign-off">
        {why}
        <p className="muted">
          {ONLY_APPROVERS} can sign this off or send it back.
        </p>
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
      <div className="sign-off-actions">
        <button type="button" onClick={signOff} disabled={busy}>
          Sign off as {handler.name}
        </button>
        <SendBack claimId={claimId} onSentBack={onSignedOff} />
      </div>
      {problem && <p role="alert">{problem}</p>}
    </div>
  );
}

/** Send the decision back to the agent with a note saying what to look at again. */
function SendBack({
  claimId,
  onSentBack,
}: Readonly<{ claimId: string; onSentBack: () => void }>) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  if (!open) {
    return (
      <button
        type="button"
        className="secondary"
        onClick={() => {
          setOpen(true);
        }}
      >
        Send back
      </button>
    );
  }

  const send = () => {
    if (!note.trim()) {
      setProblem("Say what the agent should look at again.");
      return;
    }
    setBusy(true);
    setProblem("");
    void postForRefusal(`/api/claims/${claimId}/send-back`, { note }).then(
      (refusal) => {
        setBusy(false);
        if (refusal) setProblem(refusal);
        else onSentBack();
      },
    );
  };

  return (
    <div className="send-back">
      <label htmlFor="send-back-note">
        What should the agent look at again?
      </label>
      <textarea
        id="send-back-note"
        value={note}
        maxLength={NOTE_LENGTH}
        required
        onChange={(event) => {
          setNote(event.target.value);
        }}
      />
      <p className="muted">
        <span className="mono">{note.length.toLocaleString("en-US")}</span> of{" "}
        <span className="mono">{NOTE_LENGTH.toLocaleString("en-US")}</span>{" "}
        characters
      </p>
      <div className="sign-off-actions">
        <button type="button" onClick={send} disabled={busy}>
          Send back to the agent
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => {
            setOpen(false);
            setProblem("");
          }}
        >
          Cancel
        </button>
      </div>
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
