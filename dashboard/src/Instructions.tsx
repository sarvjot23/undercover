import { useJson } from "./hooks";

interface AgentInstructions {
  queue: string;
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
        Read only. These are the instructions the UnderCover Agent works from.
      </p>
      <h3>Working the queue</h3>
      <div className="panel">
        <pre className="instructions">{data.queue}</pre>
      </div>
      <h3>Working a claim</h3>
      <div className="panel">
        <pre className="instructions">{data.claim}</pre>
      </div>
    </section>
  );
}
