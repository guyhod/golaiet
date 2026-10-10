import { useEffect } from "react";
import type { ReactNode } from "react";

/** A panel in the centre of the screen over the overview. Escape, the
 *  backdrop or the view's own close button closes it. */
export function Module({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="backdrop" onClick={onClose}>
      <div className="module" role="dialog" onClick={(event) => event.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}
