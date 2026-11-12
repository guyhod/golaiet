// The focus stream sends the current focus on every connect, not only when it changes: a page load,
// a reconnect after the Mac slept. A focus is one event (the row's set_at names it), and one that this
// browser has already acted on is not acted on again, or a drawer opened days ago would reopen on
// every load of the wall.

const KEY = "golaiet.focus.handled";
let handled: string | null = null;

type Store = Pick<Storage, "getItem" | "setItem">;

function browserStore(): Store | null {
  try {
    return window.localStorage;
  } catch {
    return null; // a private window: remembered for this load only
  }
}

/** True the first time this browser is asked about the focus set at `setAt`. */
export function firstTime(setAt: string, store: Store | null = browserStore()): boolean {
  if (handled === setAt || store?.getItem(KEY) === setAt) return false;
  handled = setAt;
  store?.setItem(KEY, setAt);
  return true;
}
