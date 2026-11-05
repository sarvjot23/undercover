import type { DiffLine } from "./api";

const MARKS: Record<DiffLine["kind"], string> = {
  same: " ",
  add: "+",
  remove: "−",
  gap: "⋯",
};

/** What a version changed, line by line: additions and removals in color. A
 * first version, with nothing before it, is shown as plain text. */
export function DiffView({
  lines,
  label,
  first = false,
}: Readonly<{ lines: DiffLine[]; label: string; first?: boolean }>) {
  if (first) {
    return (
      <pre className="instructions" aria-label={label}>
        {lines.map((line) => line.text).join("\n")}
      </pre>
    );
  }
  if (lines.length === 0) {
    return <p className="muted">No change to the text.</p>;
  }
  return (
    <div className="diff" role="group" aria-label={label}>
      {lines.map((line, index) => {
        const key = `${String(index)}-${line.kind}`;
        const body = (
          <>
            <span className="diff-mark" aria-hidden="true">
              {MARKS[line.kind]}
            </span>
            <span className="diff-text">{line.text || " "}</span>
          </>
        );
        if (line.kind === "add") {
          return (
            <ins key={key} className="diff-line diff-add">
              {body}
            </ins>
          );
        }
        if (line.kind === "remove") {
          return (
            <del key={key} className="diff-line diff-remove">
              {body}
            </del>
          );
        }
        return (
          <div key={key} className={`diff-line diff-${line.kind}`}>
            {body}
          </div>
        );
      })}
    </div>
  );
}
