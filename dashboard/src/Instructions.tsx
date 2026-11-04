import { useJson } from "./hooks";

interface AgentInstructions {
  claim: string;
}

export function Instructions() {
  const { data, error } = useJson<AgentInstructions>("/api/instructions");

  if (error) return <p role="alert">The backend is not responding.</p>;
  if (!data) return <p>Loading the instructions</p>;

  return (
    <section aria-labelledby="instructions-heading">
      <h2 id="instructions-heading">The agent&rsquo;s instructions</h2>
      <p className="muted">
        Read only. These are the instructions the claim agent works from. The
        dispatcher that hands it the claims is code, with no model and no
        instructions.
      </p>
      <h3>Working a claim</h3>
      <div className="panel">
        <pre className="instructions">{data.claim}</pre>
      </div>
    </section>
  );
}
