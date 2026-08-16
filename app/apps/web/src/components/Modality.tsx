/** Визуализация трёх модальностей. Общее правило §14.2: единая шкала, полоса
 *  шума нарисована, цвет кодирует направление только когда оно установлено. */

export interface Channel { muscle: string; label: string; left?: number; right?: number }

/** ЭМГ: парные каналы, зеркальная шкала. Асимметрия читается формой, а не числом. */
export function EmgMirror({ channels, unit = "мкВ" }: { channels: Channel[]; unit?: string }) {
  const rows = channels.filter((c) => c.left !== undefined || c.right !== undefined);
  if (!rows.length) return <div className="empty">Нет каналов ЭМГ</div>;
  const max = Math.max(...rows.flatMap((c) => [c.left ?? 0, c.right ?? 0])) * 1.1 || 1;
  const W = 720, mid = W / 2, half = 250, rowH = 30;
  const H = rows.length * rowH + 34;

  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="ЭМГ по сторонам">
      <text x={mid - half / 2} y={12} textAnchor="middle" fontSize="10.5" fill="var(--text-3)">слева</text>
      <text x={mid + half / 2} y={12} textAnchor="middle" fontSize="10.5" fill="var(--text-3)">справа</text>
      <line x1={mid} y1={18} x2={mid} y2={H - 8} stroke="var(--stroke-strong)" />
      {rows.map((c, i) => {
        const y = 30 + i * rowH;
        const lw = ((c.left ?? 0) / max) * half;
        const rw = ((c.right ?? 0) / max) * half;
        const asym = c.left && c.right
          ? (200 * (c.right - c.left)) / (Math.abs(c.right) + Math.abs(c.left)) : null;
        // Асимметрия выше 20% подсвечивается формой — обводкой, не цветом:
        // направление «лучше/хуже» для ЭМГ не установлено.
        const strong = asym !== null && Math.abs(asym) > 20;
        return (
          <g key={c.muscle}>
            <rect x={mid - lw} y={y - 8} width={lw} height={16} rx="4"
                  fill="var(--accent)" opacity={0.62}
                  stroke={strong ? "var(--accent)" : "none"} strokeWidth="1.5" />
            <rect x={mid} y={y - 8} width={rw} height={16} rx="4"
                  fill="var(--accent-2)" opacity={0.62}
                  stroke={strong ? "var(--accent-2)" : "none"} strokeWidth="1.5" />
            <text x={mid} y={y + 4} textAnchor="middle" fontSize="10" fill="var(--text)"
                  style={{ paintOrder: "stroke", stroke: "var(--surface-solid)", strokeWidth: 3 }}>
              {c.label}
            </text>
            <text x={mid - half - 12} y={y + 4} textAnchor="end" fontSize="10.5"
                  fill="var(--text-2)" style={{ fontVariantNumeric: "tabular-nums" }}>
              {c.left?.toFixed(1) ?? "—"}
            </text>
            <text x={mid + half + 12} y={y + 4} fontSize="10.5" fill="var(--text-2)"
                  style={{ fontVariantNumeric: "tabular-nums" }}>
              {c.right?.toFixed(1) ?? "—"} {unit}
            </text>
            {asym !== null && (
              <text x={mid} y={y + 17} textAnchor="middle" fontSize="8.5"
                    fill={strong ? "var(--text-2)" : "var(--text-3)"}>
                асимметрия {asym > 0 ? "+" : ""}{asym.toFixed(0)}%
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

export interface CondylarMetric { base: string; label: string; unit: string; r?: number; l?: number }

/** Кондилография: профиль SCI по амплитудам открывания — форма суставного пути.
 *  Расхождение кривых сторон и есть суставной сигнал §9.5. */
export function CondylarProfile({ metrics }: { metrics: CondylarMetric[] }) {
  const sci = [3, 5, 10].map((mm) => metrics.find((m) => m.base === `CDG_SCI_${mm}MM`));
  if (!sci.some(Boolean)) return <div className="empty">Нет углов SCI</div>;
  const points = sci.map((m, i) => ({ mm: [3, 5, 10][i], r: m?.r, l: m?.l }));
  const values = points.flatMap((p) => [p.r, p.l]).filter((v): v is number => v !== undefined);
  const min = Math.min(...values) - 6, max = Math.max(...values) + 6;
  const W = 720, H = 240, padL = 56, padB = 40, padT = 24;
  const x = (i: number) => padL + (i / (points.length - 1)) * (W - padL - 40);
  const y = (v: number) => padT + (1 - (v - min) / (max - min)) * (H - padT - padB);
  const path = (side: "r" | "l") =>
    points.map((p, i) => (p[side] === undefined ? "" : `${i ? "L" : "M"}${x(i)},${y(p[side]!)}`)).join(" ");

  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label="Профиль суставного угла SCI по амплитудам">
      {[0, 0.5, 1].map((t) => (
        <g key={t}>
          <line x1={padL} y1={padT + t * (H - padT - padB)} x2={W - 40}
                y2={padT + t * (H - padT - padB)} stroke="var(--stroke)" strokeDasharray="3 5" />
          <text x={padL - 10} y={padT + t * (H - padT - padB) + 4} textAnchor="end"
                fontSize="10" fill="var(--text-3)">
            {(max - t * (max - min)).toFixed(0)}°
          </text>
        </g>
      ))}
      <path d={path("r")} fill="none" stroke="var(--accent-2)" strokeWidth="2.5" strokeLinecap="round" />
      <path d={path("l")} fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" />
      {points.map((p, i) => (
        <g key={p.mm}>
          {p.r !== undefined && <circle cx={x(i)} cy={y(p.r)} r="4.5" fill="var(--accent-2)" />}
          {p.l !== undefined && <circle cx={x(i)} cy={y(p.l)} r="4.5" fill="var(--accent)" />}
          <text x={x(i)} y={H - 14} textAnchor="middle" fontSize="10.5" fill="var(--text-3)">
            {p.mm} мм
          </text>
          {p.r !== undefined && p.l !== undefined && (
            <text x={x(i)} y={Math.min(y(p.r), y(p.l)) - 10} textAnchor="middle" fontSize="9"
                  fill="var(--text-2)">
              Δ {Math.abs(p.r - p.l).toFixed(1)}°
            </text>
          )}
        </g>
      ))}
      <g transform={`translate(${W - 150}, ${padT})`}>
        <rect x="0" y="-4" width="10" height="10" rx="2" fill="var(--accent-2)" />
        <text x="16" y="5" fontSize="10.5" fill="var(--text-2)">справа</text>
        <rect x="70" y="-4" width="10" height="10" rx="2" fill="var(--accent)" />
        <text x="86" y="5" fontSize="10.5" fill="var(--text-2)">слева</text>
      </g>
    </svg>
  );
}

/** Три сигнала пробы на одной шкале: поза, сустав, мышца (§9.5). */
export function SignalTriad({ posture, joint, muscle, threshold }: {
  posture: number | null; joint: number | null; muscle: number | null; threshold: number;
}) {
  const rows = [
    { key: "поза", value: posture, hint: "Δ индекса отзывчивости" },
    { key: "сустав", value: joint, hint: "изменение асимметрии мыщелков, %" },
    { key: "мышца", value: muscle, hint: "ΔMI, отдельный индекс" },
  ];
  const scale = Math.max(threshold * 2.4, ...rows.map((r) => Math.abs(r.value ?? 0)) ) * 1.12;
  const W = 720, padL = 92, rowH = 34, H = rows.length * rowH + 26;
  const plot = W - padL - 90;
  const x = (v: number) => padL + plot / 2 + (v / scale) * (plot / 2);

  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Три сигнала пробы">
      <rect x={x(-threshold)} y={16} width={x(threshold) - x(-threshold)} height={H - 26}
            fill="var(--noise-band)" rx="6" />
      <text x={x(0)} y={11} textAnchor="middle" fontSize="10" fill="var(--text-3)">
        порог значимости
      </text>
      <line x1={x(0)} y1={16} x2={x(0)} y2={H - 8} stroke="var(--stroke-strong)" />
      {rows.map((r, i) => {
        const y = 32 + i * rowH;
        if (r.value === null) {
          return (
            <g key={r.key}>
              <text x={padL - 12} y={y + 4} textAnchor="end" fontSize="11.5" fill="var(--text-3)">
                {r.key}
              </text>
              <text x={x(0) + 12} y={y + 4} fontSize="10.5" fill="var(--text-3)">не измерено</text>
            </g>
          );
        }
        const noise = Math.abs(r.value) < threshold;
        return (
          <g key={r.key}>
            <text x={padL - 12} y={y + 1} textAnchor="end" fontSize="11.5" fill="var(--text-2)">
              {r.key}
            </text>
            <text x={padL - 12} y={y + 12} textAnchor="end" fontSize="8.5" fill="var(--text-3)">
              {r.hint}
            </text>
            <rect x={Math.min(x(0), x(r.value))} y={y - 8}
                  width={Math.max(2, Math.abs(x(r.value) - x(0)))} height={16} rx="8"
                  fill={noise ? "var(--neutral)" : r.value < 0 ? "var(--good)" : "var(--bad)"}
                  opacity={noise ? 0.32 : 0.85} />
            <text x={W - 78} y={y + 4} fontSize="11" fill="var(--text-2)"
                  style={{ fontVariantNumeric: "tabular-nums" }}>
              {r.value > 0 ? "+" : ""}{r.value.toFixed(2)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
