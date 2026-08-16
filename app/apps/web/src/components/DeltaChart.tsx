import type { ParamEffect } from "../lib/api";

/** График сравнения параметров.
 *
 *  MUST §14.2.1: полоса ±SDC присутствует на КАЖДОМ графике сравнения —
 *  зона шума рисуется, а не описывается словами.
 *  MUST §14.2.2: единая шкала для всей панели, автомасштаб на строку запрещён.
 *  Ось — в единицах SDC, поэтому параметры с разными единицами сравнимы честно.
 */
export function DeltaChart({ params, rowHeight = 28 }: { params: ParamEffect[]; rowHeight?: number }) {
  const rows = params.filter((p) => p.sdc !== null && p.effect_size !== null);
  if (!rows.length) {
    return <div className="empty">Нет параметров с откалиброванным SDC — эффект не нормируется</div>;
  }

  const maxAbs = Math.max(2.2, ...rows.map((r) => Math.abs(r.effect_size!))) * 1.12;
  const W = 720, padL = 236, padR = 60;
  const plot = W - padL - padR;
  const H = rows.length * rowHeight + 36;
  const x = (v: number) => padL + plot / 2 + (v / maxAbs) * (plot / 2);

  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label="Изменение параметров в единицах SDC с полосой шума">
      <rect x={x(-1)} y={20} width={x(1) - x(-1)} height={H - 30} fill="var(--noise-band)" rx="6" />
      <text x={x(0)} y={13} textAnchor="middle" fontSize="10.5" fill="var(--text-3)">
        зона шума ±1 SDC
      </text>
      <line x1={x(0)} y1={20} x2={x(0)} y2={H - 12} stroke="var(--stroke-strong)" strokeWidth="1" />
      {[-2, 2].map((t) => (
        <g key={t}>
          <line x1={x(t)} y1={20} x2={x(t)} y2={H - 12} stroke="var(--stroke)"
                strokeWidth="1" strokeDasharray="3 4" />
          <text x={x(t)} y={H - 2} textAnchor="middle" fontSize="9.5" fill="var(--text-3)">
            {t > 0 ? "+" : ""}{t} SDC
          </text>
        </g>
      ))}

      {rows.map((p, i) => {
        const y = 32 + i * rowHeight;
        const e = p.effect_size!;
        const inNoise = Math.abs(e) < 1;
        const color = inNoise || p.interpretation === null ? "var(--neutral)"
          : p.interpretation === "improving" ? "var(--good)" : "var(--bad)";
        return (
          <g key={p.code}>
            <text x={padL - 12} y={y + 3} textAnchor="end" fontSize="11.5" fill="var(--text-2)">
              {p.label_ru.length > 30 ? p.label_ru.slice(0, 29) + "…" : p.label_ru}
            </text>
            {p.direction === "unknown" && !inNoise && (
              <text x={padL - 12} y={y + 14} textAnchor="end" fontSize="8.5" fill="var(--text-3)">
                направление не установлено
              </text>
            )}
            <line x1={x(0)} y1={y} x2={x(e)} y2={y} stroke={color} strokeWidth="2.5"
                  strokeLinecap="round" opacity={inNoise ? 0.45 : 0.9} />
            <circle cx={x(e)} cy={y} r={inNoise ? 3 : 4.5} fill={color} opacity={inNoise ? 0.5 : 1} />
            <text x={W - padR + 10} y={y + 3} fontSize="11" fill="var(--text-2)"
                  style={{ fontVariantNumeric: "tabular-nums" }}>
              {p.delta > 0 ? "+" : ""}{p.delta.toFixed(1)} {p.unit}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** Отклики проб на единой шкале индекса. Пробы без установленного знака
 *  рисуются нейтрально: величина известна, направление — нет (Р-18). */
export function ResponseChart({ items }: {
  items: { probe_code: string; delta: number | null; confidence: string;
           direction_known: boolean; pass_no: number }[];
}) {
  const rows = items.filter((r) => r.delta !== null);
  if (!rows.length) return <div className="empty">Нет откликов</div>;
  const maxAbs = Math.max(1.5, ...rows.map((r) => Math.abs(r.delta!))) * 1.14;
  const W = 720, padL = 254, padR = 64, rowH = 30;
  const plot = W - padL - padR;
  const H = rows.length * rowH + 32;
  const x = (v: number) => padL + plot / 2 + (v / maxAbs) * (plot / 2);

  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Отклики проб">
      <line x1={x(0)} y1={16} x2={x(0)} y2={H - 10} stroke="var(--stroke-strong)" />
      <text x={x(0)} y={10} textAnchor="middle" fontSize="10" fill="var(--text-3)">нейтраль</text>
      {rows.map((r, i) => {
        const y = 30 + i * rowH;
        const noise = r.confidence === "noise" || r.confidence === "undefined";
        const color = noise || !r.direction_known ? "var(--neutral)"
          : r.delta! < 0 ? "var(--good)" : "var(--bad)";
        return (
          <g key={`${r.probe_code}-${r.pass_no}`}>
            <text x={padL - 12} y={y + 4} textAnchor="end" fontSize="11" fill="var(--text-2)">
              {r.probe_code}{r.pass_no > 1 ? ` · проход ${r.pass_no}` : ""}
            </text>
            <rect x={Math.min(x(0), x(r.delta!))} y={y - 7}
                  width={Math.max(2, Math.abs(x(r.delta!) - x(0)))} height={14} rx="7"
                  fill={color} opacity={noise ? 0.3 : 0.85} />
            <text x={W - padR + 10} y={y + 4} fontSize="11" fill="var(--text-2)"
                  style={{ fontVariantNumeric: "tabular-nums" }}>
              {r.delta! > 0 ? "+" : ""}{r.delta!.toFixed(2)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
