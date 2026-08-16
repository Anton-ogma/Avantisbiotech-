import type { RegionOut } from "../lib/api";

/** Схема «от сустава до стоп» (§14.3): области сверху вниз, окрашены по
 *  наибольшему по модулю отклику среди выбранных проб.
 *
 *  Цвет кодирует ВЕЛИЧИНУ, а не направление: направление большинства параметров
 *  не установлено (Р-18), и красить область в «хорошо/плохо» было бы враньём.
 *  Шкала — насыщенность акцента, подпись рядом всегда текстовая (§14 A11y). */

/** Силуэт и подписи. Подписи разнесены на 22 px по вертикали: каждая несёт две
 *  строки, и при меньшем шаге они наезжают друг на друга.
 *  label_ru нужен и для областей БЕЗ данных — иначе на схеме проступают
 *  внутренние ключи вроде `leg_axis`, которых пользователь не знает. */
const SHAPES: Record<string, { d: string; y: number; label_ru: string }> = {
  tmj:            { d: "M50,14 a13,13 0 1,0 0.1,0 Z", y: 16, label_ru: "ВНЧС и мыщелки" },
  masticatory:    { d: "M38,24 h24 a6,6 0 0 1 0,12 h-24 a6,6 0 0 1 0,-12 Z", y: 38, label_ru: "Жевательные мышцы" },
  neck:           { d: "M44,38 h12 v10 h-12 Z", y: 60, label_ru: "Шея" },
  spine_frontal:  { d: "M34,50 h32 a5,5 0 0 1 5,5 v18 a5,5 0 0 1 -5,5 h-32 a5,5 0 0 1 -5,-5 v-18 a5,5 0 0 1 5,-5 Z", y: 82, label_ru: "Позвоночник · фронталь" },
  spine_sagittal: { d: "M36,80 h28 a5,5 0 0 1 5,5 v14 a5,5 0 0 1 -5,5 h-28 a5,5 0 0 1 -5,-5 v-14 a5,5 0 0 1 5,-5 Z", y: 104, label_ru: "Позвоночник · сагитталь" },
  pelvis:         { d: "M32,106 h36 a6,6 0 0 1 6,6 v10 a6,6 0 0 1 -6,6 h-36 a6,6 0 0 1 -6,-6 v-10 a6,6 0 0 1 6,-6 Z", y: 126, label_ru: "Таз" },
  leg_axis:       { d: "M36,130 h10 v30 h-10 Z M54,130 h10 v30 h-10 Z", y: 148, label_ru: "Ось ног" },
  shank:          { d: "M37,162 h8 v28 h-8 Z M55,162 h8 v28 h-8 Z", y: 170, label_ru: "Голени" },
  feet:           { d: "M32,192 h16 a4,4 0 0 1 0,8 h-16 a4,4 0 0 1 0,-8 Z M52,192 h16 a4,4 0 0 1 0,8 h-16 a4,4 0 0 1 0,-8 Z", y: 192, label_ru: "Стопы" },
};
const LABEL_X = 84;

export function BodyMap({ regions, active, onPick }: {
  regions: RegionOut[]; active: string; onPick: (key: string) => void;
}) {
  const magnitude = (r: RegionOut) => {
    let best = 0;
    for (const row of r.rows) {
      for (const cell of Object.values(row.cells)) {
        if (cell.effect_size !== null) best = Math.max(best, Math.abs(cell.effect_size));
      }
    }
    return best;
  };
  const byKey = new Map(regions.map((r) => [r.key, r]));
  const max = Math.max(1, ...regions.map(magnitude));

  return (
    <svg className="chart" viewBox="0 0 300 212" role="img"
         aria-label="Схема областей от сустава до стоп с величиной отклика">
      {Object.entries(SHAPES).map(([key, shape]) => {
        const region = byKey.get(key);
        const m = region ? magnitude(region) : 0;
        const has = Boolean(region);
        const isActive = key === active;
        const opacity = has ? 0.18 + 0.62 * Math.min(1, m / max) : 0.08;
        return (
          <g key={key} onClick={() => has && onPick(key)}
             style={{ cursor: has ? "pointer" : "default" }}
             role={has ? "button" : undefined} tabIndex={has ? 0 : undefined}
             onKeyDown={(e) => { if (has && (e.key === "Enter" || e.key === " ")) onPick(key); }}>
            <path d={shape.d} fill="var(--accent)" opacity={opacity}
                  stroke={isActive ? "var(--accent)" : "var(--stroke-strong)"}
                  strokeWidth={isActive ? 2 : 1} />
            <line x1={70} y1={shape.y - 3} x2={LABEL_X - 4} y2={shape.y - 3}
                  stroke="var(--stroke)" strokeWidth="0.8" />
            <text x={LABEL_X} y={shape.y} fontSize="8.5"
                  fill={isActive ? "var(--text)" : has ? "var(--text-2)" : "var(--text-3)"}
                  fontWeight={isActive ? 600 : 400}>
              {region?.label_ru ?? shape.label_ru}
            </text>
            <text x={LABEL_X} y={shape.y + 9} fontSize="7.5" fill="var(--text-3)">
              {has ? (m > 0 ? `макс. эффект ${m.toFixed(1)} SDC` : "в пределах шума") : "нет данных"}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** Сгруппированные столбики по параметрам области: по одному на каждую выбранную
 *  пробу. Полоса ±1 SDC нарисована, шкала единая по всей области (§14.2). */
export function RegionBars({ region, columns, palette }: {
  region: RegionOut;
  columns: { code: string; label_ru: string }[];
  palette: string[];
}) {
  const rows = region.rows.filter((r) =>
    Object.values(r.cells).some((c) => c.effect_size !== null));
  if (!rows.length) {
    return (
      <div className="empty">
        {region.structural
          ? "Структурная область: выводится без Δ (§14.2 п. 8)"
          : "Нет параметров с откалиброванным SDC"}
      </div>
    );
  }
  const maxAbs = Math.max(2.2, ...rows.flatMap((r) =>
    Object.values(r.cells).map((c) => Math.abs(c.effect_size ?? 0)))) * 1.12;

  const W = 720, padL = 206, padR = 130;
  const plot = W - padL - padR;
  const barH = 13, gap = 4;
  const groupH = columns.length * (barH + gap) + 14;
  const H = rows.length * groupH + 34;
  const x = (v: number) => padL + plot / 2 + (v / maxAbs) * (plot / 2);

  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label={`Отклик в области «${region.label_ru}» по выбранным пробам`}>
      <rect x={x(-1)} y={20} width={x(1) - x(-1)} height={H - 30} fill="var(--noise-band)" rx="6" />
      <text x={x(0)} y={13} textAnchor="middle" fontSize="10" fill="var(--text-3)">
        зона шума ±1 SDC
      </text>
      <line x1={x(0)} y1={20} x2={x(0)} y2={H - 12} stroke="var(--stroke-strong)" />
      {[-2, 2].map((t) => (
        <line key={t} x1={x(t)} y1={20} x2={x(t)} y2={H - 12}
              stroke="var(--stroke)" strokeDasharray="3 4" />
      ))}

      {rows.map((row, ri) => {
        const top = 30 + ri * groupH;
        return (
          <g key={row.code}>
            <text x={padL - 12} y={top + 9} textAnchor="end" fontSize="11" fill="var(--text-2)">
              {row.label_ru.length > 28 ? row.label_ru.slice(0, 27) + "…" : row.label_ru}
            </text>
            <text x={padL - 12} y={top + 20} textAnchor="end" fontSize="8" fill="var(--text-3)">
              {row.unit}{row.direction === "unknown" ? " · направление не установлено" : ""}
            </text>
            {columns.map((col, ci) => {
              const cell = row.cells[col.code];
              const y = top + ci * (barH + gap);
              if (!cell || cell.effect_size === null) {
                return (
                  <text key={col.code} x={W - padR + 12} y={y + barH - 3} fontSize="9"
                        fill="var(--text-3)">нет данных</text>
                );
              }
              const e = cell.effect_size;
              const noise = Math.abs(e) < 1;
              return (
                <g key={col.code}>
                  <rect x={Math.min(x(0), x(e))} y={y} width={Math.max(2, Math.abs(x(e) - x(0)))}
                        height={barH} rx="3" fill={palette[ci % palette.length]}
                        opacity={noise ? 0.3 : 0.9} />
                  <text x={e < 0 ? x(e) - 6 : x(e) + 6} y={y + barH - 3}
                        textAnchor={e < 0 ? "end" : "start"} fontSize="9" fill="var(--text-2)"
                        style={{ fontVariantNumeric: "tabular-nums" }}>
                    {cell.delta! > 0 ? "+" : ""}{cell.delta!.toFixed(1)}
                  </text>
                </g>
              );
            })}
          </g>
        );
      })}
    </svg>
  );
}
