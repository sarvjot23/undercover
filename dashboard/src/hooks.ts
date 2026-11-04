import { useEffect, useState } from "react";
import { getJson, postForRefusal } from "./api";

export type Route =
  | { view: "queue" }
  | { view: "claim"; claimId: string }
  | { view: "configuration" }
  | { view: "settings" }
  | { view: "scoreboard" }
  | { view: "evaluation"; runId: number }
  | { view: "live" };

export function parseRoute(hash: string): Route {
  const claim = /^#\/claims\/([\w-]+)$/.exec(hash);
  if (claim?.[1]) return { view: "claim", claimId: claim[1] };
  // The Instructions page became the Configuration page.
  if (hash === "#/configuration" || hash === "#/instructions")
    return { view: "configuration" };
  if (hash === "#/settings") return { view: "settings" };
  if (hash === "#/scoreboard") return { view: "scoreboard" };
  const evaluation = /^#\/scoreboard\/(\d+)$/.exec(hash);
  if (evaluation?.[1])
    return { view: "evaluation", runId: Number(evaluation[1]) };
  if (hash === "#/live") return { view: "live" };
  return { view: "queue" };
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const update = () => {
      setRoute(parseRoute(window.location.hash));
    };
    window.addEventListener("hashchange", update);
    return () => {
      window.removeEventListener("hashchange", update);
    };
  }, []);
  return route;
}

export interface Loaded<T> {
  data: T | undefined;
  error: boolean;
  reload: () => void;
}

/**
 * Fetch JSON from the backend. `every` gives the wait in ms before fetching
 * again, as a number or from the data just loaded; 0 stops. Pass a stable value.
 */
export function useJson<T>(
  path: string,
  every: number | ((data: T) => number) = 0,
): Loaded<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = () => {
      getJson<T>(path).then(
        (value) => {
          if (!live) return;
          setData(value);
          setError(false);
          const wait = typeof every === "number" ? every : every(value);
          if (wait > 0) timer = setTimeout(load, wait);
        },
        () => {
          if (live) setError(true);
        },
      );
    };
    load();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [path, every, version]);

  return {
    data,
    error,
    reload: () => {
      setVersion((v) => v + 1);
    },
  };
}

export function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Count up from 0 to `target` over `ms`, or show it at once with reduced motion. */
export function useCountUp(target: number, ms = 900): number {
  const [value, setValue] = useState(() =>
    prefersReducedMotion() ? target : 0,
  );
  useEffect(() => {
    if (prefersReducedMotion()) return;
    const started = Date.now();
    const timer = setInterval(() => {
      const t = Math.min(1, (Date.now() - started) / ms);
      setValue(target * (1 - (1 - t) ** 3));
      if (t === 1) clearInterval(timer);
    }, 30);
    return () => {
      clearInterval(timer);
    };
  }, [target, ms]);
  return value;
}

export function enterFullscreen(): void {
  document.documentElement.requestFullscreen().catch(() => undefined);
}

export function exitFullscreen(): void {
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => undefined);
  }
}

export const DEFAULT_AGENTS = 3;
export const MAX_AGENTS = 25;

/** Hold a number of claim agents between 1 and 25. */
export function agentsAtOnce(value: number): number {
  return Number.isNaN(value)
    ? DEFAULT_AGENTS
    : Math.min(MAX_AGENTS, Math.max(1, Math.round(value)));
}

/**
 * Start a dispatch with N claim agents at once and watch it in the live view.
 * Return the reason if it was refused, such as the agent's service not running.
 */
export async function startDispatch(n: number): Promise<string | null> {
  enterFullscreen();
  const refusal = await postForRefusal("/api/dispatches", { n });
  if (refusal) {
    exitFullscreen();
    return refusal;
  }
  window.location.hash = "#/live";
  return null;
}

export function leaveLiveView(): void {
  exitFullscreen();
  window.location.hash = "#/";
}
