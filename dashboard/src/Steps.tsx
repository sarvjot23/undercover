import type { Step } from "./api";

const KINDS: Record<Step["kind"], string> = {
  check: "Security check",
  tool_call: "Calls",
  tool_result: "Result",
  lookup: "Looked up",
  memory_search: "Searched memory",
  memory_save: "Saved to memory",
  refusal: "Refused",
  send_back: "Sent back",
  answer: "Answer",
  error: "Error",
};

/** The step's label: a refusal says who refused, such as the Gateway, and a send
 * back who sent the decision back. */
function kindOf(step: Step): string {
  if (step.kind === "refusal") return `Refused by ${step.detail.by}`;
  if (step.kind === "send_back") return `Sent back by ${step.detail.by}`;
  return KINDS[step.kind];
}

/** The step's text; a refusal's leaves out who refused, which its label says. */
function textOf(step: Step): string {
  return step.kind === "refusal"
    ? step.text.replace(`Refused by ${step.detail.by}: `, "")
    : step.text;
}

/** Where a lookup's answer came from: each file with its system. */
function Sources({ step }: Readonly<{ step: Step }>) {
  if (step.kind !== "lookup") return null;
  if (step.detail.files.length === 0) {
    return <span className="step-source">Nothing found</span>;
  }
  return (
    <span className="step-source">
      From{" "}
      {step.detail.files
        .map((file) => `${file.file} (${file.system})`)
        .join(", ")}
    </span>
  );
}

export function Steps({ steps }: Readonly<{ steps: Step[] }>) {
  if (steps.length === 0) {
    return (
      <p className="muted">The agent hasn&rsquo;t worked on this claim.</p>
    );
  }
  return (
    <ol className="steps">
      {steps.map((step) => (
        <li key={step.step_id} className={`step step-${step.kind}`}>
          <span className="step-kind">{kindOf(step)}</span>
          <span className="step-body">
            <span className="step-text">{textOf(step)}</span>
            <Sources step={step} />
          </span>
        </li>
      ))}
    </ol>
  );
}
