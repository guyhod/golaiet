import { useEffect, useState } from "react";
import { getJson } from "./api";

export const REFRESH_MS = 60_000;

export type Polled<T> = { data: T | null; error: string | null; at: Date | null };

/** One endpoint, read now and again every interval while the component is shown.
 *  The last answer stands through a failure, with the error beside it; a new
 *  path starts empty; a null path reads nothing. Every screen reads this way. */
export function usePolled<T>(path: string | null, intervalMs = REFRESH_MS): Polled<T> {
  const [polled, setPolled] = useState<Polled<T>>({ data: null, error: null, at: null });
  useEffect(() => {
    setPolled({ data: null, error: null, at: null });
    if (!path) return;
    let cancelled = false;
    const load = () =>
      getJson<T>(path)
        .then((data) => !cancelled && setPolled({ data, error: null, at: new Date() }))
        .catch((failure) => !cancelled && setPolled((last) => ({ ...last, error: String(failure) })));
    load();
    const timer = setInterval(load, intervalMs);
    return () => { cancelled = true; clearInterval(timer); };
  }, [path, intervalMs]);
  return polled;
}
