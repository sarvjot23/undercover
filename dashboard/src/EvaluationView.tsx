import type { Evaluation, Outcome, ScoredClaim } from "./api";
import {
  averageGrade,
  check,
  claimsLabel,
  cost,
  grade,
  duration,
  money,
  OUTCOME_LABELS,
  percent,
  SET_LABELS,
} from "./format";
import { useJson } from "./hooks";
import { Badge, ErrorState, LoadingState, PageHeader } from "./ui";

/** Follow an evaluation while it runs. */
function pollEvaluation(evaluation: Evaluation): number {
  return evaluation.status === "running" ? 2000 : 0;
}

function answer(decision: Outcome, payout: number): string {
  return decision === "approve"
    ? `${OUTCOME_LABELS[decision]} ${money(payout)}`
    : OUTCOME_LABELS[decision];
}

/** One evaluation: its measures, and each claim with the handler's answer beside the agent's. */
export function EvaluationView({ runId }: Readonly<{ runId: number }>) {
  const { data: evaluation, error } = useJson<Evaluation>(
    `/api/evaluations/${String(runId)}`,
    pollEvaluation,
  );

  if (error) {
    return (
      <ErrorState message={`There is no evaluation ${String(runId)}.`}>
        <a href="#/scoreboard">Back to the scoreboard</a> to choose another.
      </ErrorState>
    );
  }
  if (!evaluation) return <LoadingState what="the evaluation" />;

  const { scores } = evaluation;
  const misses = evaluation.claims.filter((claim) => !claim.right).length;

  return (
    <section aria-labelledby="evaluation-heading">
      <a href="#/scoreboard">Back to the scoreboard</a>
      <PageHeader
        title={`Evaluation ${String(evaluation.run_id)}`}
        id="evaluation-heading"
      >
        {evaluation.set_name ? SET_LABELS[evaluation.set_name] : ""},{" "}
        {claimsLabel(evaluation.tiny).toLowerCase()}, with{" "}
        <span className="mono">{evaluation.n}</span> claim agents at once on{" "}
        <span className="mono">{evaluation.model}</span> (reasoning{" "}
        {evaluation.reasoning}), version{" "}
        <span className="mono">{evaluation.version}</span>
      </PageHeader>
      {evaluation.status === "running" && (
        <p role="status">Running: the measures follow when it finishes.</p>
      )}
      {evaluation.status === "stopped" && (
        <p role="status">
          Stopped partway, so it has no measures. These are the claims it got
          through.
        </p>
      )}
      {scores && (
        <dl className="run-figures panel">
          <div>
            <dt>Decision accuracy</dt>
            <dd className="mono">{percent(scores.decision_accuracy)}</dd>
          </div>
          <div>
            <dt>Accuracy</dt>
            <dd className="mono">{percent(scores.accuracy)}</dd>
          </div>
          <div>
            <dt>Cost of mistakes</dt>
            <dd className="mono">{money(scores.cost_of_mistakes)}</dd>
          </div>
          <div>
            <dt>Grade</dt>
            <dd className="mono">{averageGrade(scores.grade)}</dd>
          </div>
          <div>
            <dt>Straight through</dt>
            <dd className="mono">{percent(scores.straight_through)}</dd>
          </div>
          <div>
            <dt>Model cost</dt>
            <dd className="mono">
              {cost(scores.cost)}, {cost(scores.cost_per_claim)} a claim
            </dd>
          </div>
          <div>
            <dt>Time per claim</dt>
            <dd className="mono">{duration(scores.seconds_per_claim)}</dd>
          </div>
          <div>
            <dt>Run time</dt>
            <dd className="mono">{duration(scores.seconds)}</dd>
          </div>
          <div>
            <dt>Judge&rsquo;s cost</dt>
            <dd className="mono">{cost(scores.judge_cost)}</dd>
          </div>
        </dl>
      )}
      <p>
        <span className="mono">{misses}</span> of{" "}
        <span className="mono">{evaluation.claims.length}</span> claims missed
      </p>
      <div className="panel table-panel">
        <table>
          <thead>
            <tr>
              <th scope="col">Claim</th>
              <th scope="col">Copied from</th>
              <th scope="col">Handler</th>
              <th scope="col">Agent</th>
              <th scope="col">Result</th>
              <th scope="col">Grade</th>
              <th scope="col">Same grounds</th>
              <th scope="col">Same section</th>
              <th scope="col" className="number">
                Cost of the mistake
              </th>
              <th scope="col" className="number">
                Model cost
              </th>
              <th scope="col" className="number">
                Time
              </th>
            </tr>
          </thead>
          <tbody>
            {evaluation.claims.map((claim) => (
              <ClaimRow key={claim.claim_id} claim={claim} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ClaimRow({ claim }: Readonly<{ claim: ScoredClaim }>) {
  return (
    <tr className={claim.right ? undefined : "miss"}>
      <td className="mono">
        <a href={`#/claims/${claim.claim_id}`}>{claim.claim_id}</a>
      </td>
      <td className="mono">{claim.source_id}</td>
      <td>{answer(claim.handler_decision, claim.handler_payout)}</td>
      <td>
        {claim.decision
          ? answer(claim.agent_decision, claim.agent_payout)
          : "Not decided, counted as a referral"}
      </td>
      <td>
        <Badge tone={claim.right ? "steel" : "burnished"}>
          {claim.right ? "Right" : "Miss"}
        </Badge>
      </td>
      <td className="mono">{grade(claim.letter, claim.grade)}</td>
      <td>{check(claim.same_grounds)}</td>
      <td>{check(claim.same_section)}</td>
      <td className="mono number">
        {claim.right ? "" : money(claim.mistake_cost)}
      </td>
      <td className="mono number">{cost(claim.cost)}</td>
      <td className="mono number">{duration(claim.seconds)}</td>
    </tr>
  );
}
