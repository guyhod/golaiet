import { useEffect, useMemo, useRef, useState } from "react";
import { usePolled } from "../../polled";
import { CampaignMap } from "./CampaignMap";
import { Drawer } from "./Drawer";
import { BurningPanel, FocusPanel, HorizonBar, Legend, NextPanel, PulseRow, PulseTile } from "./Panels";
import { campaignsOn, findLane, selectionFor } from "./lookup";
import type { Board, Selection } from "./types";

// The Life screen: Guy's practices along the top, what is burning and in focus, the week ahead, the map
// of his campaigns, the next actions and what passed. On a wide window it is one fixed 1920×1080 canvas
// scaled to fit, so the wall shows everything and nothing scrolls; on a narrow one the same parts flow
// down the page and the drawer is a sheet from the bottom.

const CANVAS = { width: 1920, height: 1080 };
const WIDE_FROM = 1200;
// The room the map has inside its card on the canvas; a taller map is scaled down to it.
const MAP_ROOM = 650;
// The wall has no keyboard and nobody near it: a drawer a conversation opened closes by itself.
const PUSHED_DRAWER_MS = 90_000;

export type Pushed = { slug: string; params: Record<string, unknown>; at: string };

/** The size of the box the screen has, kept current, to choose the layout and the canvas scale. */
function useBox() {
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: window.innerWidth, height: window.innerHeight });
  useEffect(() => {
    if (!box.current) return;
    const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(box.current);
    return () => observer.disconnect();
  }, []);
  return { box, size };
}

export function Life({ wall, pushed }: { wall: boolean; pushed: Pushed | null }) {
  const { data: board, error, at } = usePolled<Board>("/api/life");
  const { box, size } = useBox();
  const [selection, setSelection] = useState<Selection | null>(null);
  const [filterDate, setFilterDate] = useState<string | null>(null);

  // A focus pushed from a conversation opens what it names, once the board is here to find it on.
  const boardReady = board !== null;
  useEffect(() => {
    if (!pushed || !board) return;
    setSelection(selectionFor(board, pushed.slug, pushed.params));
    if (!wall) return;
    const timer = setTimeout(() => setSelection(null), PUSHED_DRAWER_MS);
    return () => clearTimeout(timer);
  }, [pushed?.at, boardReady]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (selection) setSelection(null);
      else setFilterDate(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selection]);

  const due = useMemo(() => (board && filterDate ? campaignsOn(board, filterDate) : null), [board, filterDate]);

  if (!board) {
    return <div className="life" ref={box}><p className="empty">{error ? `Cannot load the board: ${error}` : "Loading the board…"}</p></div>;
  }

  const select = (campaign: string, station?: string) =>
    setSelection(station ? { kind: "station", campaign, station } : { kind: "lane", campaign });
  const openSource = (source: string, station?: string) => {
    const lane = findLane(board, source);
    if (lane) select(lane.id, station);
  };
  const next = due ? board.next.filter((action) => due.has(findLane(board, action.source)?.id ?? "")) : board.next;
  const filterLabel = filterDate ? board.horizon.find((day) => day.date === filterDate)?.label ?? filterDate : null;
  const onMap = selection && selection.kind !== "practice"
    ? { campaign: selection.campaign, station: selection.kind === "station" ? selection.station : undefined }
    : null;
  const today = new Date(`${board.today}T00:00:00`);
  const dateBlock = (
    <div className="date-block">
      <div className="date">
        {today.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })} <span>{today.getFullYear()}</span>
      </div>
      <div className="updated">
        {at ? `Updated ${at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })}` : ""}
        {error ? " · the last read failed" : ""}
      </div>
    </div>
  );
  const pulseSelected = selection?.kind === "practice" ? selection.id : undefined;
  const panels = {
    burning: (area?: string) => <BurningPanel items={board.burning} more={board.burning_more} style={{ gridArea: area }} onSelect={setSelection} />,
    focus: (area?: string) => <FocusPanel items={board.focus} style={{ gridArea: area }} onSelect={setSelection} />,
    horizon: (area?: string) => <HorizonBar horizon={board.horizon} filterDate={filterDate} style={{ gridArea: area }} onFilter={setFilterDate} onSelect={setSelection} />,
    next: (area?: string) => <NextPanel next={next} trail={board.trail} filterLabel={filterLabel} style={{ gridArea: area }} onClearFilter={() => setFilterDate(null)} onSource={openSource} />,
  };

  if (size.width >= WIDE_FROM) {
    const scale = Math.min(size.width / CANVAS.width, size.height / CANVAS.height);
    return (
      <div className="life fit" ref={box}>
        <div className="canvas" style={{ transform: `scale(${scale})` }}>
          <div className="wall-grid">
            <div className="wall-head" style={{ gridArea: "head" }}>
              {dateBlock}
              <PulseRow pulse={board.pulse} selectedId={pulseSelected} onSelect={setSelection} />
            </div>
            {panels.burning("burning")}
            {panels.focus("focus")}
            {panels.horizon("horizon")}
            <section className="card map-card" style={{ gridArea: "map" }}>
              <CampaignMap lanes={board.lanes} maxHeight={MAP_ROOM} onSelect={select} selected={onMap} dim={due} />
            </section>
            {panels.next("next")}
            <Legend quiet={board.quiet} style={{ gridArea: "legend" }} />
          </div>
          {selection && <Drawer selection={selection} board={board} sheet={false} onClose={() => setSelection(null)} onSelect={setSelection} />}
        </div>
      </div>
    );
  }

  return (
    <div className="life flow" ref={box}>
      {dateBlock}
      <div className="pulse-grid">
        {board.pulse.map((tile) => <PulseTile key={tile.id} tile={tile} selected={pulseSelected === tile.id} onSelect={setSelection} />)}
      </div>
      {panels.burning()}
      {panels.focus()}
      {panels.horizon()}
      <section className="card map-card scrolls">
        <CampaignMap lanes={board.lanes} onSelect={select} selected={onMap} dim={due} />
      </section>
      {panels.next()}
      <Legend quiet={board.quiet} />
      {selection && <Drawer selection={selection} board={board} sheet onClose={() => setSelection(null)} onSelect={setSelection} />}
    </div>
  );
}
