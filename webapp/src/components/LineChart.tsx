interface Props {
  time: number[];
  values: number[];
  color: string;
  unit: string;
}

/** SVG line chart ported from the design prototype (x-axis in hours). */
export function LineChart({ time, values, color, unit }: Props) {
  if (!time.length || !values.length) return null;
  const W = 560, H = 185;
  const P = { l: 50, r: 14, t: 12, b: 28 };
  const iw = W - P.l - P.r, ih = H - P.t - P.b;
  const tMax = Math.max(time[time.length - 1], 1);
  let vmin = Math.min(...values), vmax = Math.max(...values);
  const pad = (vmax - vmin) * 0.12 || 1;
  vmin -= pad;
  vmax += pad;
  const X = (t: number) => P.l + (t / tMax) * iw;
  const Y = (v: number) => P.t + ih - ((v - vmin) / (vmax - vmin)) * ih;
  const pts = time.map((t, i) => `${X(t)},${Y(values[i])}`).join(" ");

  const yTicks = [0, 1, 2, 3].map((k) => {
    const v = vmin + ((vmax - vmin) * k) / 3;
    return { y: Y(v), text: k === 3 ? v.toFixed(0) + " " + unit : v.toFixed(v > 1000 ? 0 : 1) };
  });
  const hoursMax = tMax / 3600;
  const xHours = [0, 0.25, 0.5, 0.75, 1].map((f) => f * hoursMax);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block" }}>
      {yTicks.map((t, k) => (
        <text key={"yt" + k} x={P.l - 7} y={t.y + 3} textAnchor="end" fontSize={9} fill="#9aa1a9" fontFamily="IBM Plex Mono">
          {t.text}
        </text>
      ))}
      {xHours.map((hr, k) => (
        <text key={"xt" + k} x={X(hr * 3600)} y={H - 9} textAnchor="middle" fontSize={9} fill="#9aa1a9" fontFamily="IBM Plex Mono">
          {hoursMax >= 2 ? Math.round(hr) + "h" : (hr * 60).toFixed(0) + "m"}
        </text>
      ))}
      <line x1={P.l} y1={P.t} x2={P.l} y2={P.t + ih} stroke="#e4e7ea" strokeWidth={1} />
      <line x1={P.l} y1={P.t + ih} x2={P.l + iw} y2={P.t + ih} stroke="#e4e7ea" strokeWidth={1} />
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
