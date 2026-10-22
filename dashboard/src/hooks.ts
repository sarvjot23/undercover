import { useEffect, useState } from "react";
import { getJson } from "./api";

export type Route =
  | { view: "queue" }
  | { view: "claim"; claimId: string }
  | { view: "instructions" }
  | { view: "live" };

export function parseRoute(hash: string): Route {
  const claim = /^#\/claims\/([\w-]+)$/.exec(hash);
  if (claim?.[1]) return { view: "claim", claimId: claim[1] };
  if (hash === "#/instructions") return { view: "instructions" };
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

export function leaveLiveView(): void {
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => undefined);
  }
  window.location.hash = "#/";
}
