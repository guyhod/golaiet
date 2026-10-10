import type { ComponentType } from "react";
import { Feed } from "./Feed";

export type ViewProps = { slug: string; params: Record<string, unknown>; onBack: () => void };

/** A tracker kind names its view; every kind gets `feed` for free. */
const VIEWS: Record<string, ComponentType<ViewProps>> = { feed: Feed };

export function viewFor(name: string): ComponentType<ViewProps> {
  return VIEWS[name] ?? Feed;
}
