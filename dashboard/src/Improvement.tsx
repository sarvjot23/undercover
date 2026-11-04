import { useState } from "react";
import type { Handler, Round } from "./api";
import { postForRefusal } from "./api";
import { ConfirmDialog } from "./ConfirmDialog";
import { cost, dateTime, percent } from "./format";
import { ONLY_APPROVERS, useCanApprove } from "./handler";
import { useJson } from "./hooks";
import { Recipes } from "./Recipes";
import { RoundProposal } from "./RoundProposal";
import { ROUND_STATUS, isOpen, shownStage, STAGES, VERDICTS } from "./rounds";
import { VersionChart } from "./VersionChart";

/** Follow the rounds closely while one is open. */
function pollRounds(rounds: Round[]): number {
  return rounds.some(isOpen) ? 2000 : 10000;
}

/** The Improvement page: rounds of the improver, run by our handlers. */
export function Improvement() {
  const {
    data: rounds,
    error,
    reload,
  } = useJson<Round[]>("/api/rounds", pollRounds);
  const { data: handlers } = useJson<Handler[]>("/api/handlers");
  const canAct = useCanApprove();
  const [confirming, setConfirming] = useState<"start" | "stop" | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  const open = rounds?.find(isOpen);

  const act = () => {
    const path =
      confirming === "stop" && open
        ? `/api/rounds/${String(open.round_id)}/stop`
        : "/api/rounds";
    setConfirming(null);
    void postForRefusal(path).then((refused) => {
      setRefusal(refused);
      reload();
    });
  };

  return (
    <section aria-labelledby="improvement-heading">
      <h2 id="improvement-heading">Improvement</h2>
      <p className="muted">
        The improver reads the claim agent&rsquo;s results and proposes changes.
        Nothing takes effect until a handler approves it, and our rule keeps a
        new version only if it does better on claims the improver never sees.
      </p>
      <div className="queue-head">
        {canAct ? (
          <>
            <button
              type="button"
              disabled={!rounds || Boolean(open)}
              onClick={() => {
                setConfirming("start");
              }}
            >
              Start a round
            </button>
            {open && (
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setConfirming("stop");
                }}
              >
                Stop the round
              </button>
            )}
          </>
        ) : (
          <p className="note">
            {ONLY_APPROVERS} can start or stop a round, or approve or reject the
            improver&rsquo;s proposals.
          </p>
        )}
      </div>
      {refusal && <p role="alert">{refusal}</p>}
      {error && <p role="alert">The backend is not responding.</p>}
      {!error && !rounds && <p className="placeholder">Loading the rounds</p>}
      {open && <OpenRound round={open} onDecided={reload} />}
      {rounds && (
        <>
          <section className="panel spaced" aria-labelledby="chart-heading">
            <h3 id="chart-heading">Each version tried, on the held-out set</h3>
            <VersionChart rounds={rounds} />
          </section>
          <RoundsTable rounds={rounds} handlers={handlers} />
        </>
      )}
      <Recipes />
      {confirming === "start" && (
        <ConfirmDialog
          title="Start a round?"
          confirmLabel="Start a round"
          onConfirm={act}
          onCancel={() => {
            setConfirming(null);
          }}
        >
          <p>
            The round works to the settings as they stand now, and spends up to
            its limit on the improver, its evaluations and the judge.
          </p>
        </ConfirmDialog>
      )}
      {confirming === "stop" && (
        <ConfirmDialog
          title="Stop the round?"
          confirmLabel="Stop the round"
          onConfirm={act}
          onCancel={() => {
            setConfirming(null);
          }}
        >
          <p>
            Before its verdict, the current version stays as it is. After it,
            the verdict stands.
          </p>
        </ConfirmDialog>
      )}
    </section>
  );
}

/** Where the open round has got to, and any proposal waiting. */
function OpenRound({
  round,
  onDecided,
}: Readonly<{ round: Round; onDecided: () => void }>) {
  const current = STAGES.findIndex(([stage]) => stage === shownStage(round));
  return (
    <>
      <section className="panel spaced" aria-labelledby="open-round-heading">
        <h3 id="open-round-heading">
          Round {round.round_id}{" "}
          <span className={`badge badge-round-${round.status}`}>
            {ROUND_STATUS[round.status]}
          </span>
        </h3>
        <ol className="stages" aria-label="Where the round has got to">
          {STAGES.map(([stage, label], index) => (
            <li
              key={stage}
              className={stepClass(index, current)}
              aria-current={index === current ? "step" : undefined}
            >
              {label}
              {index === current && round.progress && (
                <span className="mono"> {round.progress}</span>
              )}
            </li>
          ))}
        </ol>
        <p className="muted">
          Spent <span className="mono">{cost(round.spent)}</span> of{" "}
          <span className="mono">
            {cost(round.settings.round_spending_limit)}
          </span>
          .{round.verdict && round.why && ` ${verdictLine(round)}`}
        </p>
      </section>
      <RoundProposal round={round} onDecided={onDecided} />
    </>
  );
}

function stepClass(index: number, current: number): string | undefined {
  if (index < current) return "done";
  return index === current ? "now" : undefined;
}

function verdictLine(round: Round): string {
  const version = String(round.version_tried);
  return round.verdict === "kept"
    ? `Version ${version} was kept: ${round.why ?? ""}.`
    : `Version ${version} was rolled back: ${round.why ?? ""}.`;
}

function scoreChange(
  before: number | null | undefined,
  after: number | null | undefined,
  show: (value: number) => string,
): string {
  const shown = (value: number | null | undefined) =>
    value === null || value === undefined ? "None" : show(value);
  if (after === undefined && before === undefined) return "";
  return `${shown(before)} to ${shown(after)}`;
}

/** The rounds so far, newest first. */
function RoundsTable({
  rounds,
  handlers,
}: Readonly<{ rounds: Round[]; handlers: Handler[] | undefined }>) {
  const name = (id: string) =>
    handlers?.find((handler) => handler.handler_id === id)?.name ?? id;
  if (rounds.length === 0) {
    return (
      <p className="muted spaced">
        No rounds yet. Start a round to have the improver propose its first
        change.
      </p>
    );
  }
  return (
    <div className="panel spaced table-panel">
      <table aria-label="Rounds">
        <thead>
          <tr>
            <th scope="col">Round</th>
            <th scope="col">Status</th>
            <th scope="col">Version tried</th>
            <th scope="col" className="number">
              Held-out accuracy
            </th>
            <th scope="col" className="number">
              Held-out grade
            </th>
            <th scope="col">Verdict</th>
            <th scope="col">Approvals</th>
            <th scope="col" className="number">
              Cost
            </th>
          </tr>
        </thead>
        <tbody>
          {rounds.map((round) => (
            <tr key={round.round_id}>
              <td>
                <span className="mono">{round.round_id}</span>
                <div className="muted">
                  Recipe {round.recipe_version},{" "}
                  <span className="mono">{dateTime(round.started_at)}</span>
                </div>
              </td>
              <td>
                <span className={`badge badge-round-${round.status}`}>
                  {ROUND_STATUS[round.status]}
                </span>
              </td>
              <td>
                {round.tried ? (
                  <>
                    <span className="mono">Version {round.tried.version}</span>
                    <div className="muted">
                      {round.tried.model}, {round.tried.reasoning}
                    </div>
                    {round.reason && (
                      <div className="summary">{round.reason}</div>
                    )}
                  </>
                ) : (
                  <span className="muted">None</span>
                )}
              </td>
              <td className="mono number">
                {scoreChange(
                  round.before?.accuracy,
                  round.after?.accuracy,
                  percent,
                )}
              </td>
              <td className="mono number">
                {scoreChange(round.before?.grade, round.after?.grade, (value) =>
                  value.toFixed(2),
                )}
              </td>
              <td>
                {round.verdict ? (
                  <>
                    <span className={`badge badge-verdict-${round.verdict}`}>
                      {VERDICTS[round.verdict]}
                    </span>
                    <div className="summary">{round.why}</div>
                  </>
                ) : (
                  <span className="muted">None</span>
                )}
              </td>
              <td>
                <ul className="events">
                  {round.events.map((event) => (
                    <li key={event.event_id}>
                      {event.decision === "approve" ? "Approved" : "Rejected"}{" "}
                      the {event.proposal}: {name(event.handler_id)},{" "}
                      <span className="mono">{dateTime(event.at)}</span>
                      {event.message && (
                        <span className="muted">
                          {" "}
                          &ldquo;{event.message}&rdquo;
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </td>
              <td className="mono number">{cost(round.spent)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
