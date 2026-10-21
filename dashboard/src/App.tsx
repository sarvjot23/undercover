import { useRoute } from "./hooks";
import { Instructions } from "./Instructions";
import { Queue } from "./Queue";

export function App() {
  const route = useRoute();

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
        {route.view === "instructions" ? <Instructions /> : <Queue />}
      </main>
    </div>
  );
}
