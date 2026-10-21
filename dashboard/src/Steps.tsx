import type { Step } from "./api";

const KINDS: Record<Step["kind"], string> = {
  tool_call: "Calls",
  tool_result: "Result",
  answer: "Answer",
  error: "Error",
};

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
          <span className="step-kind">{KINDS[step.kind]}</span>
          <span className="step-text">{step.text}</span>
        </li>
      ))}
    </ol>
  );
}
