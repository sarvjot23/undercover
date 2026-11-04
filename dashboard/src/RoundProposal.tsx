import { useState } from "react";
import type { Round } from "./api";
import { postForRefusal } from "./api";
import { ModelChange } from "./Configuration";
import { ConfirmDialog } from "./ConfirmDialog";
import { DiffView } from "./DiffView";
import { useCanApprove } from "./handler";

type Choice = "approve" | "reject" | null;

/** The improver's proposal waiting for a handler: what it changes, and why. */
export function RoundProposal({
  round,
  onDecided,
}: Readonly<{ round: Round; onDecided: () => void }>) {
  const canDecide = useCanApprove();
  const [choice, setChoice] = useState<Choice>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const proposal = round.proposal;
  if (!proposal) return null;

  const what = proposal.kind === "change" ? "change" : "recipe";
  const decide = () => {
    if (!choice) return;
    setBusy(true);
    void postForRefusal(`/api/rounds/${String(round.round_id)}/decision`, {
      decision: choice,
      message: choice === "reject" ? message.trim() : "",
    }).then((refusal) => {
      setBusy(false);
      setChoice(null);
      if (refusal) {
        setProblem(refusal);
        return;
      }
      setProblem("");
      setMessage("");
      onDecided();
    });
  };

  return (
    <section
      className="panel spaced proposal"
      aria-labelledby="proposal-heading"
    >
      <h3 id="proposal-heading">
        {proposal.kind === "change"
          ? "A change to the claim agent, waiting for approval"
          : "A new recipe for the improver, waiting for approval"}
      </h3>
      <p>
        <span className="muted">The improver&rsquo;s reason:</span>{" "}
        {proposal.reason}
      </p>
      {proposal.kind === "change" && (
        <>
          <ModelChange
            label="Model"
            before={proposal.model_before}
            after={proposal.model}
          />
          <ModelChange
            label="Reasoning effort"
            before={proposal.reasoning_before}
            after={proposal.reasoning}
          />
        </>
      )}
      <DiffView
        lines={proposal.diff}
        label={
          proposal.kind === "change"
            ? "The instructions, as the change leaves them"
            : "The recipe, as the change leaves it"
        }
      />
      {problem && <p role="alert">{problem}</p>}
      {canDecide ? (
        <div className="form-actions spaced">
          <button
            type="button"
            onClick={() => {
              setChoice("approve");
            }}
          >
            Approve
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setChoice("reject");
            }}
          >
            Reject
          </button>
        </div>
      ) : (
        <p className="note spaced">
          Only a handler who can sign off payouts over the limit can approve or
          reject the improver&rsquo;s proposals.
        </p>
      )}
      {choice === "approve" && (
        <ConfirmDialog
          title={`Approve this ${what}?`}
          confirmLabel="Approve"
          busy={busy}
          onConfirm={decide}
          onCancel={() => {
            setChoice(null);
          }}
        >
          <p>
            {proposal.kind === "change"
              ? "The new version is evaluated once on the evaluation set and twice on the held-out set, then kept or rolled back by our rule."
              : "The next round follows the new recipe."}
          </p>
        </ConfirmDialog>
      )}
      {choice === "reject" && (
        <ConfirmDialog
          title={`Reject this ${what}?`}
          confirmLabel="Reject"
          busy={busy || message.trim() === ""}
          onConfirm={decide}
          onCancel={() => {
            setChoice(null);
          }}
        >
          <label className="setting">
            <span>Your reason, for the improver</span>
            <textarea
              value={message}
              onChange={(event) => {
                setMessage(event.target.value);
              }}
            />
          </label>
        </ConfirmDialog>
      )}
    </section>
  );
}
