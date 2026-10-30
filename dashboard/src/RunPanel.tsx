import type { Run } from "./api";
import { TODO_LABELS } from "./format";

const RUN_LABELS: Record<Run["status"], string> = {
  running: "The agent is working through the queue",
  finished: "The last run is finished",
  failed: "The last run stopped",
};

/** The current queue run: the agent's to-do list, ticked off as it goes, then its summary. */
export function RunPanel({ run }: Readonly<{ run: Run | null | undefined }>) {
  if (!run) return null;

  return (
    <section className="panel run-panel" aria-labelledby="run-heading">
      <div className="run-head">
        <h3 id="run-heading">The agent&rsquo;s to-do list</h3>
        <span className="muted">
          {run.status === "running" && !run.active
            ? "The last run stopped partway"
            : RUN_LABELS[run.status]}{" "}
          &middot; <span className="mono">{run.claim_ids.length}</span> of{" "}
          <span className="mono">{run.total}</span> claims taken
        </span>
      </div>
      {run.todos.length === 0 ? (
        <p className="muted">The agent is planning the run.</p>
      ) : (
        <ol className="todos">
          {run.todos.map((todo) => (
            <li key={todo.claim_id} className={`todo todo-${todo.status}`}>
              <a className="mono" href={`#/claims/${todo.claim_id}`}>
                {todo.claim_id}
              </a>
              <span className="todo-note">{todo.note}</span>
              <span className={`badge todo-badge-${todo.status}`}>
                {TODO_LABELS[todo.status]}
              </span>
            </li>
          ))}
        </ol>
      )}
      {run.status !== "running" && run.summary && (
        <div className="run-summary">
          <h4>
            {run.status === "finished"
              ? "The agent's summary"
              : "Why it stopped"}
          </h4>
          <p>{run.summary}</p>
        </div>
      )}
    </section>
  );
}
