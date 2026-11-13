import type { SourceFile, Step } from "./api";
import { date } from "./format";

interface FileUsed {
  source: SourceFile;
  lookedUp: string[];
}

/** Everything the agent looked up in the context layer, once each, by file. */
function filesUsed(steps: Step[]): FileUsed[] {
  const files = new Map<string, FileUsed>();
  for (const step of steps) {
    if (step.kind !== "lookup") continue;
    for (const source of step.detail.files) {
      const used = files.get(source.file) ?? { source, lookedUp: [] };
      if (!used.lookedUp.includes(step.detail.looked_up)) {
        used.lookedUp.push(step.detail.looked_up);
      }
      files.set(source.file, used);
    }
  }
  return [...files.values()];
}

export function ContextUsed({ steps }: Readonly<{ steps: Step[] }>) {
  const files = filesUsed(steps);
  if (files.length === 0) return null;
  return (
    <section className="panel" aria-labelledby="context-heading">
      <h3 id="context-heading">Context used</h3>
      {files.map(({ source, lookedUp }) => (
        <section
          key={source.file}
          className="context-file"
          aria-label={source.file}
        >
          <h4 className="mono">{source.file}</h4>
          <p className="muted">
            {source.system}, owned by {source.owner}, reviewed{" "}
            <span className="mono">{date(source.reviewed)}</span>
          </p>
          <ul className="reads">
            {lookedUp.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      ))}
    </section>
  );
}
