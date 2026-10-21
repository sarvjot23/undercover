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

/** Fetch JSON from the backend, again every `everyMs` while it is above 0. */
export function useJson<T>(path: string, everyMs = 0): Loaded<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState(false);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let live = true;
    const load = () => {
      getJson<T>(path).then(
        (value) => {
          if (live) {
            setData(value);
            setError(false);
          }
        },
        () => {
          if (live) setError(true);
        },
      );
    };
    load();
    const timer = everyMs > 0 ? setInterval(load, everyMs) : undefined;
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [path, everyMs, version]);

  return {
    data,
    error,
    reload: () => {
      setVersion((v) => v + 1);
    },
  };
}
