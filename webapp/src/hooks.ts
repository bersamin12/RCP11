import { useEffect, useState } from "react";

/** True when the viewport is narrower than `bp` px. */
export function useNarrow(bp = 900): boolean {
  const [narrow, setNarrow] = useState(() => window.matchMedia(`(max-width: ${bp}px)`).matches);
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${bp}px)`);
    const onChange = (e: MediaQueryListEvent) => setNarrow(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [bp]);
  return narrow;
}
