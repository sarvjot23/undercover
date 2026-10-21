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
