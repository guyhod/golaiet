import type { ComponentType } from "react";
import { Feed } from "./Feed";
import { Globe } from "./Globe";

export type ViewProps = { slug: string; params: Record<string, unknown>; onClose: () => void };
export type View = { component: ComponentType<ViewProps>; wide: boolean };

/** A tracker kind names its view; every kind gets `feed` for free. */
const VIEWS: Record<string, View> = {
  feed: { component: Feed, wide: false },
  globe: { component: Globe, wide: true },
};

export function viewFor(name: string): View {
  return VIEWS[name] ?? VIEWS.feed;
}
