import type { ReactNode } from "react";
import type { Campaign, Station, Track } from "./types";
import {
  AXIS, BORDER, CRIT, CURRENT, GOOD, GRID, INK, INK2, LANE_H, MAP_W, MUTED, PAGE, PANEL, TRACK_H, WARN,
  fmt, wrap,
} from "./palette";

/*
 * The life map: one lane per campaign, its stations along tracks. What each mark means:
 *   passed  = filled green circle          current  = blue ring + dot (bold label)
 *   ahead   = grey-stroked disc            proposed = dashed circle (muted label)
 *   decision= diamond                      ref      = dashed diamond (interchange)
 *   burning = red outer ring + "!" badge   focus    = amber outer ring
 *   edges: passed→passed green, passed→current blue, else axis; dashed = OR / into a proposed station
 */

type NodePos = { x: number; y: number; state: string };
type Nodes = Map<string, NodePos>;
const key = (cid: string, sid: string) => `${cid}.${sid}`;

function edgeColor(a: string, b: string) {
  if (a === "passed" && b === "passed") return GOOD;
  if (a === "passed" && b === "current") return CURRENT;
  return AXIS;
}

function StationGlyph({ x, y, s, selected, onClick }: { x: number; y: number; s: Station; selected?: boolean; onClick?: () => void }) {
  const r = 8;
  const parts: ReactNode[] = [];
  if (selected) parts.push(<circle key="sel" cx={x} cy={y} r={r + 11} fill="none" stroke={INK} strokeWidth={1.5} strokeDasharray="2 3" opacity={0.9} />);
  switch (s.state) {
    case "passed":
      parts.push(<circle key="p" cx={x} cy={y} r={r} fill={GOOD} />);
      break;
    case "current":
      parts.push(<circle key="c1" cx={x} cy={y} r={r + 3} fill="none" stroke={CURRENT} strokeWidth={2.5} />);
      parts.push(<circle key="c2" cx={x} cy={y} r={4} fill={CURRENT} />);
      break;
    case "ahead":
      parts.push(<circle key="a" cx={x} cy={y} r={r} fill={PANEL} stroke={MUTED} strokeWidth={2} />);
      break;
    case "proposed":
      parts.push(<circle key="pr" cx={x} cy={y} r={r} fill="none" stroke={MUTED} strokeWidth={2} strokeDasharray="3 3" />);
      break;
    case "decision":
      parts.push(
        <rect key="d" x={x - 9} y={y - 9} width={18} height={18} transform={`rotate(45 ${x} ${y})`} fill={PANEL} stroke={INK2} strokeWidth={2} />,
      );
      break;
    case "ref":
      parts.push(
        <rect key="r" x={x - 8} y={y - 8} width={16} height={16} transform={`rotate(45 ${x} ${y})`} fill="none" stroke={INK2} strokeWidth={2} strokeDasharray="3 2" />,
      );
      break;
  }
  if (s.burning) {
    parts.push(<circle key="b1" cx={x} cy={y} r={r + 7} fill="none" stroke={CRIT} strokeWidth={2} />);
    parts.push(<circle key="b2" cx={x + 13} cy={y - 13} r={7} fill={CRIT} />);
    parts.push(
      <text key="b3" x={x + 13} y={y - 9.5} fontSize={10} fontWeight={700} fill="#fff" textAnchor="middle">
        !
      </text>,
    );
  }
  if (s.focus) {
    parts.push(<circle key="f" cx={x} cy={y} r={r + 7} fill="none" stroke={WARN} strokeWidth={2} opacity={0.9} />);
  }
  if (s.options && s.options.length) {
    parts.push(
      <text key="o" x={x + 16} y={y + 4} fontSize={11} fill={MUTED}>
        {s.options.join(" · ")}
      </text>,
    );
  }
  const lines = wrap(s.label);
  const weight = s.state === "current" ? 700 : 400;
  let color = s.state === "current" || s.state === "passed" || s.state === "decision" ? INK : INK2;
  if (s.state === "proposed" || s.state === "ref") color = MUTED;
  const ty = y + 22;
  lines.forEach((ln, i) =>
    parts.push(
      <text key={`l${i}`} x={x} y={ty + i * 13} fontSize={12.5} fontWeight={weight} fill={color} textAnchor="middle">
        {ln}
      </text>,
    ),
  );
  let small: string | null = null;
  let col = MUTED;
  if (s.burning_why) {
    small = s.burning_why;
    col = CRIT;
  } else if (s.state === "passed" && s.date) small = fmt(s.date);
  else if (s.check) small = "chk " + fmt(s.check);
  else if (s.note) small = s.note;
  if (small) {
    parts.push(
      <text key="sm" x={x} y={ty + lines.length * 13 + 1} fontSize={10.5} fill={col} textAnchor="middle">
        {small}
      </text>,
    );
  }
  return (
    <g onClick={onClick} style={onClick ? { cursor: "pointer" } : undefined}>
      {onClick && <circle cx={x} cy={y} r={22} fill="transparent" />}
      {parts}
    </g>
  );
}

type Interact = {
  onSelect?: (campaign: string, station?: string) => void;
  selected?: { campaign: string; station?: string } | null;
  dim?: Set<string> | null;
};

function laneBlock(
  c: Campaign,
  x: number,
  yTop: number,
  width: number,
  titleW: number,
  dxIn: number,
  nodes: Nodes,
  ix: Interact,
): { el: ReactNode; h: number } {
  const out: ReactNode[] = [];
  const isSel = (sid?: string) => !!ix.selected && ix.selected.campaign === c.id && (sid ? ix.selected.station === sid : !ix.selected.station);
  const tracks: Track[] = c.tracks;
  const caps = tracks.map((t) => t.caption || "");
  const hasCaps = caps.some(Boolean);
  const x0 = x + (hasCaps ? 92 : 62);
  const dx = hasCaps ? Math.min(dxIn, 100) : dxIn;
  const minis = tracks.filter((t) => t.mini);
  const full = tracks.filter((t) => !t.mini);
  const nfull = Math.max(1, full.length);
  let h = nfull === 1 ? LANE_H : 12 + nfull * TRACK_H;
  const yShift = minis.length ? 36 : 0;
  h += yShift;
  const tint = c.focus ? "rgba(250,178,25,0.06)" : c.burning ? "rgba(208,59,59,0.06)" : null;
  if (tint) out.push(<rect key="tint" x={x} y={yTop} width={width} height={h} rx={8} fill={tint} />);

  full.forEach((t, ti) => {
    const y = nfull === 1 ? yTop + 24 + yShift : yTop + 24 + yShift + ti * TRACK_H;
    const sts = t.stations || [];
    const ranks = sts.map((s, i) => (s.rank ?? i));
    for (let i = 0; i < sts.length - 1; i++) {
      const a = sts[i], b = sts[i + 1];
      const xa = x0 + ranks[i] * dx, xb = x0 + ranks[i + 1] * dx;
      const dashed = b.state === "proposed" || a.join_next === "or";
      out.push(
        <line key={`e${ti}-${i}`} x1={xa + 11} y1={y} x2={xb - 11} y2={y} stroke={edgeColor(a.state, b.state)} strokeWidth={2.5}
          strokeDasharray={dashed ? "6 5" : undefined} />,
      );
    }
    sts.forEach((s, i) => {
      const xx = x0 + ranks[i] * dx;
      nodes.set(key(c.id, s.id), { x: xx, y, state: s.state });
      out.push(<StationGlyph key={`s${ti}-${s.id}`} x={xx} y={y} s={s} selected={isSel(s.id)} onClick={ix.onSelect ? () => ix.onSelect!(c.id, s.id) : undefined} />);
    });
    if (t.caption) {
      out.push(
        <text key={`cap${ti}`} x={x0 - 16} y={y + 3.5} fontSize={9.5} fontWeight={700} letterSpacing={1} fill={MUTED} textAnchor="end">
          {t.caption.toUpperCase()}
        </text>,
      );
    }
  });

  // compact gate row above the main track: node + label beside it
  minis.forEach((t, mi) => {
    const ym = yTop + 20;
    (t.stations || []).forEach((s, i) => {
      const xm = x0 + (s.rank ?? i) * dx;
      nodes.set(key(c.id, s.id), { x: xm, y: ym, state: s.state });
      const colf = s.state === "passed" ? GOOD : s.state === "current" ? CURRENT : PANEL;
      const cols = s.state === "passed" ? GOOD : s.state === "current" ? CURRENT : MUTED;
      const small = s.state === "passed" && s.date ? fmt(s.date) : s.note || "";
      const cap = t.caption ? t.caption + " · " : "";
      out.push(<circle key={`m${mi}-${s.id}`} cx={xm} cy={ym} r={7} fill={colf} stroke={cols} strokeWidth={2} onClick={ix.onSelect ? () => ix.onSelect!(c.id, s.id) : undefined} style={ix.onSelect ? { cursor: "pointer" } : undefined} />);
      out.push(
        <text key={`mt${mi}-${s.id}`} x={xm + 12} y={ym + 4} fontSize={12.5} fill={INK2}>
          {cap}
          {s.label}{" "}
          <tspan fill={MUTED} fontSize={10.5}>{small}</tspan>
        </text>,
      );
    });
  });

  // AND feeders across tracks: station.requires -> ids on other tracks
  tracks.forEach((t, ti) =>
    (t.stations || []).forEach((s) =>
      (s.requires || []).forEach((rid, ri) => {
        const A = nodes.get(key(c.id, rid)), B = nodes.get(key(c.id, s.id));
        if (!A || !B || A.y === B.y) return;
        const col = A.state === "passed" ? GOOD : AXIS;
        const dashed = s.join === "or";
        const d =
          A.y < B.y
            ? `M${A.x + 8},${A.y + 4} C${A.x + 40},${A.y + 4} ${B.x - 4},${A.y + 4} ${B.x - 2},${B.y - 11}`
            : `M${A.x + 8},${A.y - 4} C${A.x + 40},${A.y - 4} ${B.x - 4},${A.y - 4} ${B.x - 2},${B.y + 11}`;
        out.push(<path key={`rq${ti}-${s.id}-${ri}`} d={d} fill="none" stroke={col} strokeWidth={2} strokeDasharray={dashed ? "6 5" : undefined} />);
      }),
    ),
  );

  // badge pill
  const badge = c.focus ? "★ FOCUS" : c.burning ? "! BURNING" : "";
  if (badge) {
    const bcol = c.focus ? WARN : CRIT;
    const pw = c.focus ? 58 : 66;
    const px = x + width - titleW - pw - 10;
    out.push(<rect key="bp" x={px} y={yTop + 3} width={pw} height={14} rx={7} fill={bcol} />);
    out.push(
      <text key="bt" x={px + pw / 2} y={yTop + 13.5} fontSize={9.5} fontWeight={800} fill="#111" textAnchor="middle">
        {badge}
      </text>,
    );
  }

  // title bar
  const bx = x + width - titleW, by = yTop + 5, bw = titleW - 4, bh = h - 10;
  const accent = c.focus ? WARN : c.burning ? CRIT : MUTED;
  const stroke = c.focus || c.burning ? accent : BORDER;
  const laneSel = isSel();
  out.push(<rect key="tb" x={bx} y={by} width={bw} height={bh} rx={6} fill={PANEL} stroke={laneSel ? INK : stroke} strokeWidth={laneSel ? 1.5 : stroke !== BORDER ? 2 : 1} strokeDasharray={laneSel ? "3 3" : undefined} onClick={ix.onSelect ? () => ix.onSelect!(c.id) : undefined} style={ix.onSelect ? { cursor: "pointer" } : undefined} />);
  out.push(<rect key="ta" x={bx} y={by} width={4} height={bh} rx={2} fill={accent} />);
  const tl = wrap(c.title, titleW >= 160 ? 17 : 15);
  const ty = by + 18;
  tl.forEach((ln, i) =>
    out.push(
      <text key={`t${i}`} x={bx + 12} y={ty + i * 15} fontSize={13} fontWeight={700} fill={INK} style={{ pointerEvents: "none" }}>
        {ln}
      </text>,
    ),
  );
  out.push(
    <text key="tm" x={bx + 12} y={ty + tl.length * 15 + 1} fontSize={11} fill={MUTED} style={{ pointerEvents: "none" }}>
      {c._meta}
    </text>,
  );
  const dimmed = !!ix.dim && !ix.dim.has(c.id);
  return { el: <g key={`lane-${c.id}`} opacity={dimmed ? 0.22 : 1} style={{ transition: "opacity .25s" }}>{out}</g>, h };
}

export function buildMap(lanes: Campaign[], ix: Interact = {}): { el: ReactNode; height: number } {
  const parts: ReactNode[] = [];
  const nodes: Nodes = new Map();
  let y = 6;
  const wide = lanes.filter((c) => c._wide);
  const cards = lanes.filter((c) => !c._wide);
  for (const c of wide) {
    const { el, h } = laneBlock(c, 0, y, MAP_W, 200, 104, nodes, ix);
    parts.push(el);
    y += h;
    parts.push(<line key={`sep-${c.id}`} x1={0} y1={y} x2={MAP_W} y2={y} stroke={GRID} />);
  }
  // interchanges (ref stations) — orthogonal dashed connectors
  for (const c of lanes)
    for (const t of c.tracks)
      for (const s of t.stations || []) {
        if (s.ref && s.ref.includes(".")) {
          const [cid, sid] = s.ref.split(".", 2) as [string, string];
          const A = nodes.get(key(cid, sid)), B = nodes.get(key(c.id, s.id));
          if (A && B) {
            const down = B.y > A.y;
            const ym = down ? A.y + 44 : A.y - 30;
            parts.push(
              <path key={`ref-${c.id}-${s.id}`} d={`M${A.x},${down ? A.y + 11 : A.y - 11} V${ym} H${B.x} V${down ? B.y - 11 : B.y + 11}`}
                fill="none" stroke={INK2} strokeWidth={2} strokeDasharray="4 3" />,
            );
            parts.push(
              <text key={`reft-${c.id}-${s.id}`} x={B.x + 12} y={ym + 12} fontSize={10.5} fill={MUTED}>
                interchange
              </text>,
            );
          }
        }
      }
  y += 10;
  const colW = 600, gap = 30;
  // distribute cards into two columns by height balance
  const cols: Campaign[][] = [[], []];
  const heights = [0, 0];
  for (const c of cards) {
    const nfull = Math.max(1, c.tracks.filter((t) => !t.mini).length);
    const hh = (nfull === 1 ? LANE_H : 12 + nfull * TRACK_H) + (c.tracks.some((t) => t.mini) ? 36 : 0) + 16;
    const i = heights[0] <= heights[1] ? 0 : 1;
    cols[i].push(c);
    heights[i] += hh;
  }
  const yStart = y;
  let yMax = y;
  cols.forEach((ids, ci) => {
    const cx = ci * (colW + gap);
    let cy = yStart;
    for (const c of ids) {
      const { el, h } = laneBlock(c, cx + 8, cy + 4, colW - 16, 138, 104, nodes, ix);
      parts.push(<rect key={`card-${c.id}`} x={cx} y={cy} width={colW} height={h + 8} rx={10} fill={PAGE} stroke={BORDER} />);
      parts.push(el);
      cy += h + 8 + 8;
    }
    yMax = Math.max(yMax, cy);
  });
  return { el: <>{parts}</>, height: yMax };
}

export function CampaignMap({ lanes, maxHeight, onSelect, selected, dim }: { lanes: Campaign[]; maxHeight?: number } & Interact) {
  const { el, height } = buildMap(lanes, { onSelect, selected, dim });
  const scale = maxHeight ? Math.min(1, maxHeight / height) : 1;
  return (
    <div style={{ width: MAP_W * scale, height: height * scale }}>
      <svg
        viewBox={`0 0 ${MAP_W} ${height}`}
        width={MAP_W}
        height={height}
        style={{ display: "block", transform: `scale(${scale})`, transformOrigin: "top left" }}
        fontFamily="system-ui,-apple-system,Segoe UI,sans-serif"
      >
        {el}
      </svg>
    </div>
  );
}
