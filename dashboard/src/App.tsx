import type { Handler } from "./api";
import { signOut, useSession } from "./auth";
import { ClaimView } from "./ClaimView";
import { Configuration } from "./Configuration";
import { EvaluationView } from "./EvaluationView";
import { HandlerContext } from "./handler";
import type { Route } from "./hooks";
import { useJson, useRoute } from "./hooks";
import { LiveView } from "./LiveView";
import { Queue } from "./Queue";
import { Scoreboard } from "./Scoreboard";
import { Settings } from "./Settings";
import { SignIn } from "./SignIn";

export function App() {
  const session = useSession();
  if (session === undefined) return <p className="page">Loading</p>;
  if (session === null) return <SignIn />;
  return <SignedIn email={session.user.email ?? ""} />;
}

/** Every page, for a signed-in handler, found among our handlers by email. */
function SignedIn({ email }: Readonly<{ email: string }>) {
  const route = useRoute();
  const { data: handlers } = useJson<Handler[]>("/api/handlers");
  const handler = handlers?.find((found) => found.email === email) ?? null;

  return (
    <HandlerContext value={handler}>
      {route.view === "live" ? (
        <LiveView />
      ) : (
        <div className="page">
          <Masthead route={route} handler={handler} email={email} />
          <main>
            <Page route={route} />
          </main>
        </div>
      )}
    </HandlerContext>
  );
}

function Page({ route }: Readonly<{ route: Route }>) {
  switch (route.view) {
    case "claim":
      return <ClaimView key={route.claimId} claimId={route.claimId} />;
    case "scoreboard":
      return <Scoreboard />;
    case "evaluation":
      return <EvaluationView key={route.runId} runId={route.runId} />;
    case "configuration":
      return <Configuration />;
    case "settings":
      return <Settings />;
    default:
      return <Queue />;
  }
}

function Masthead({
  route,
  handler,
  email,
}: Readonly<{ route: Route; handler: Handler | null; email: string }>) {
  const here = (...views: Route["view"][]) =>
    views.includes(route.view) ? ("page" as const) : undefined;
  return (
    <header className="masthead">
      <a href="#/" className="brand">
        UnderCover
      </a>
      <span className="tagline">Claims, decided with care</span>
      <nav aria-label="Main">
        <a href="#/" aria-current={here("queue", "claim")}>
          Queue
        </a>
        <a href="#/scoreboard" aria-current={here("scoreboard", "evaluation")}>
          Scoreboard
        </a>
        <a href="#/configuration" aria-current={here("configuration")}>
          Configuration
        </a>
        <a href="#/settings" aria-current={here("settings")}>
          Settings
        </a>
      </nav>
      <div className="who">
        <span>
          <strong>{handler?.name ?? email}</strong>
          {handler && <span className="muted"> {handler.role}</span>}
        </span>
        <button
          type="button"
          className="quiet"
          onClick={() => {
            void signOut();
          }}
        >
          Sign out
        </button>
      </div>
    </header>
  );
}
