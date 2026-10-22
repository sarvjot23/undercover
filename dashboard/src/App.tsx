import { ClaimView } from "./ClaimView";
import { useRoute } from "./hooks";
import { Instructions } from "./Instructions";
import { LiveView } from "./LiveView";
import { Queue } from "./Queue";

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
      </main>
    </div>
  );
}
