import { ClaimView } from "./ClaimView";
import { EvaluationView } from "./EvaluationView";
import { useRoute } from "./hooks";
import { Instructions } from "./Instructions";
import { LiveView } from "./LiveView";
import { Queue } from "./Queue";
import { Scoreboard } from "./Scoreboard";

export function App() {
  const route = useRoute();

  if (route.view === "live") return <LiveView />;

  return (
    <div className="page">
      <header className="masthead">
        <a href="#/" className="brand">
          UnderCover
        </a>
        <span className="tagline">Claims, decided with care</span>
        <nav aria-label="Main">
          <a
            href="#/"
            aria-current={route.view === "queue" ? "page" : undefined}
          >
            Queue
          </a>
          <a
            href="#/scoreboard"
            aria-current={
              route.view === "scoreboard" || route.view === "evaluation"
                ? "page"
                : undefined
            }
          >
            Scoreboard
          </a>
          <a
            href="#/instructions"
            aria-current={route.view === "instructions" ? "page" : undefined}
          >
            Instructions
          </a>
        </nav>
      </header>
      <main>
        {route.view === "instructions" && <Instructions />}
        {route.view === "claim" && (
          <ClaimView key={route.claimId} claimId={route.claimId} />
        )}
        {route.view === "queue" && <Queue />}
        {route.view === "scoreboard" && <Scoreboard />}
        {route.view === "evaluation" && (
          <EvaluationView key={route.runId} runId={route.runId} />
        )}
      </main>
    </div>
  );
}
