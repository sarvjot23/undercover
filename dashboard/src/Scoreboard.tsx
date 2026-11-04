import { useState } from "react";
import type { EvaluationSummary, Run, Scores, SetName } from "./api";
import { postForRefusal } from "./api";
import {
  averageGrade,
  claimsLabel,
  cost,
  duration,
  money,
  percent,
  SET_LABELS,
} from "./format";
import { DEFAULT_AGENTS, useJson } from "./hooks";
import { AgentsAtOnce } from "./Queue";

const STATUS_LABELS: Record<Run["status"], string> = {
  running: "Running",
  finished: "Finished",
  stopped: "Stopped",
};

/** The Scoreboard: start an evaluation, and every evaluation's measures. */
export function Scoreboard() {
  const {
    data: evaluations,
    error,
    reload,
  } = useJson<EvaluationSummary[]>("/api/evaluations", 3000);
  const { data: running } = useJson<Run | null>("/api/runs/running", 1500);
  const [setName, setSetName] = useState<SetName>("evaluation");
  const [tiny, setTiny] = useState(false);
  const [agents, setAgents] = useState(DEFAULT_AGENTS);
  const [refusal, setRefusal] = useState<string | null>(null);

  if (error) return <p role="alert">The backend is not responding.</p>;
  if (!evaluations) return <p>Loading the scoreboard</p>;

  const start = () => {
    setRefusal(null);
    void postForRefusal("/api/evaluations", {
      set_name: setName,
      tiny,
      n: agents,
    }).then((refused) => {
      setRefusal(refused);
      reload();
    });
  };

  return (
    <section aria-labelledby="scoreboard-heading">
      <h2 id="scoreboard-heading">Scoreboard</h2>
      <p className="muted">
        Each evaluation works copies of a labelled set&rsquo;s claims and scores
        the agent against our handlers&rsquo; decisions. The copies never reach
        the queue.
      </p>
      <div className="panel evaluation-form">
        <label className="cap">
          Labelled set
          <select
            value={setName}
            onChange={(event) => {
              setSetName(event.target.value as SetName);
            }}
          >
            <option value="evaluation">{SET_LABELS.evaluation}</option>
            <option value="held_out">{SET_LABELS.held_out}</option>
          </select>
        </label>
        <label className="cap">
          Claims
          <select
            value={tiny ? "tiny" : "whole"}
            onChange={(event) => {
              setTiny(event.target.value === "tiny");
            }}
          >
            <option value="whole">{claimsLabel(false)}</option>
            <option value="tiny">{claimsLabel(true)}</option>
          </select>
        </label>
        <AgentsAtOnce value={agents} onChange={setAgents} />
        <button type="button" onClick={start} disabled={Boolean(running)}>
          Start an evaluation
        </button>
      </div>
      {running && (
        <p role="status">A dispatch or evaluation is already running</p>
      )}
      {refusal && <p role="alert">{refusal}</p>}
      {evaluations.length === 0 ? (
        <p className="muted">No evaluations yet.</p>
      ) : (
        <div className="panel table-panel">
          <table>
            <thead>
              <tr>
                <th scope="col">Evaluation</th>
                <th scope="col">Set</th>
                <th scope="col">Claims</th>
                <th scope="col" className="number">
                  N
                </th>
                <th scope="col">Model</th>
                <th scope="col">Status</th>
                <th scope="col" className="number">
                  Decision accuracy
                </th>
                <th scope="col" className="number">
                  Accuracy
                </th>
                <th scope="col" className="number">
                  Cost of mistakes
                </th>
                <th scope="col" className="number">
                  Grade
                </th>
                <th scope="col" className="number">
                  Straight through
                </th>
                <th scope="col" className="number">
                  Cost per claim
                </th>
                <th scope="col" className="number">
                  Time per claim
                </th>
                <th scope="col" className="number">
                  Run time
                </th>
                <th scope="col" className="number">
                  Judge&rsquo;s cost
                </th>
              </tr>
            </thead>
            <tbody>
              {evaluations.map((evaluation) => (
                <EvaluationRow
                  key={evaluation.run_id}
                  evaluation={evaluation}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function EvaluationRow({
  evaluation,
}: Readonly<{ evaluation: EvaluationSummary }>) {
  const scores = evaluation.scores;
  return (
    <tr>
      <td>
        <a href={`#/scoreboard/${String(evaluation.run_id)}`}>
          Evaluation {evaluation.run_id}
        </a>
      </td>
      <td>{evaluation.set_name ? SET_LABELS[evaluation.set_name] : ""}</td>
      <td>{claimsLabel(evaluation.tiny)}</td>
      <td className="mono number">{evaluation.n}</td>
      <td className="mono">
        {evaluation.model} ({evaluation.reasoning})
      </td>
      <td>{STATUS_LABELS[evaluation.status]}</td>
      <Measures scores={scores} />
    </tr>
  );
}

/** An evaluation's measures as table cells, blank until it has finished. */
function Measures({ scores }: Readonly<{ scores: Scores | null }>) {
  const cells: [string, string][] = [
    ["decision_accuracy", scores ? percent(scores.decision_accuracy) : ""],
    ["accuracy", scores ? percent(scores.accuracy) : ""],
    ["cost_of_mistakes", scores ? money(scores.cost_of_mistakes) : ""],
    ["grade", scores ? averageGrade(scores.grade) : ""],
    ["straight_through", scores ? percent(scores.straight_through) : ""],
    ["cost_per_claim", scores ? cost(scores.cost_per_claim) : ""],
    ["seconds_per_claim", scores ? duration(scores.seconds_per_claim) : ""],
    ["seconds", scores ? duration(scores.seconds) : ""],
    ["judge_cost", scores ? cost(scores.judge_cost) : ""],
  ];
  return (
    <>
      {cells.map(([name, cell]) => (
        <td key={name} className="mono number">
          {cell}
        </td>
      ))}
    </>
  );
}
