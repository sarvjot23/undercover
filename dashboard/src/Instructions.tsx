import { useJson } from "./hooks";

export function Instructions() {
  const { data, error } = useJson<{ text: string }>("/api/instructions");

  if (error) return <p role="alert">The backend is not responding.</p>;
  if (!data) return <p>Loading the instructions</p>;

  return (
    <section aria-labelledby="instructions-heading">
      <h2 id="instructions-heading">The agent&rsquo;s instructions</h2>
      <p className="muted">
        Read only. These are the instructions the UnderCover Agent works from.
      </p>
      <div className="panel">
        <pre className="instructions">{data.text}</pre>
      </div>
    </section>
  );
}
