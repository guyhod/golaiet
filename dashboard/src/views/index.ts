import type { ComponentType } from "react";
import { Feed } from "./Feed";
import { Price } from "./Price";

export type ViewProps = { slug: string; params: Record<string, unknown>; onClose: () => void };
export type View = { component: ComponentType<ViewProps>; wide: boolean };

/** A tracker kind names its view; every kind gets `feed` for free. The views
 *  here open as a module; `globe` is the screen itself (App.tsx). */
const VIEWS: Record<string, View> = {
  feed: { component: Feed, wide: false },
  price: { component: Price, wide: true },
};

export function viewFor(name: string): View {
  return VIEWS[name] ?? VIEWS.feed;
}
