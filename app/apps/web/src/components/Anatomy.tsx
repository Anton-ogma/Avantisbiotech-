/** Анатомические схемы, построенные ИЗ ИЗМЕРЕНИЙ (§14.2, Р-40).
 *
 *  Зачем свои схемы, если протокол прибора уже печатает иллюстрации: печатная
 *  иллюстрация существует для одной пробы и одного визита — сравнить по ней
 *  четыре пробы нельзя. Здесь та же геометрия строится из параметров, поэтому
 *  схемы выстраиваются рядом и читаются как один ряд.
 *
 *  ЖЁСТКОЕ ПРАВИЛО: рисуется только то, что измерено.
 *  Угол проводится под измеренным углом, длина — в измеренном масштабе, размах
 *  движения — веером от границы до границы. Форма кривой позвоночника прибором
 *  в этот протокол не выгружается, поэтому она и НЕ рисуется: вместо выдуманной
 *  S-образной кривой показан коридор ±max отклонения и метка rms. Нарисовать
 *  правдоподобную кривую значило бы показать врачу форму, которой в данных нет.
 */

export type Values = Record<string, number>;

/** Значение по первому найденному коду: статика и динамика — разные величины,
 *  и порядок кодов задаёт вызывающий, а не эвристика внутри. */
export function pick(values: Values, ...codes: string[]): number | null {
  for (const c of codes) if (typeof values[c] === "number") return values[c];
  return null;
}

const fmt = (v: number, unit: string) =>
  `${v > 0 ? "+" : ""}${Number.isInteger(v) ? v : v.toFixed(1)} ${unit}`;
/** Сторона словом — как печатает прибор. Канон знака: вправо положительно (§5.3). */
const side = (v: number) => (v > 0 ? "Прав." : v < 0 ? "Лев." : "—");

function Caption({ text, sub }: { text: string; sub?: string }) {
  return (
    <div className="fig-caption">
      <span>{text}</span>
      {sub && <span className="fig-sub">{sub}</span>}
    </div>
  );
}

function NoData({ title, why }: { title: string; why: string }) {
  return (
    <div className="fig">
      <div className="fig-title">{title}</div>
      <div className="fig-empty">{why}</div>
    </div>
  );
}

/* ── Таз, вид сзади: линия перекоса под измеренным углом ──────────────────── */

export function PelvisFrontal({ values, label }: { values: Values; label?: string }) {
  const angle = pick(values, "PELVIC_OBLIQUITY_ANGLE", "DYN_PELVIC_OBLIQUITY_ANGLE");
  const mm = pick(values, "PELVIC_OBLIQUITY_DL_DR", "DYN_PELVIC_OBLIQUITY");
  const lo = pick(values, "DYN_PELVIC_OBLIQUITY_ANGLE_ROM_MIN");
  const hi = pick(values, "DYN_PELVIC_OBLIQUITY_ANGLE_ROM_MAX");

  if (angle === null && mm === null) {
    return <NoData title="Таз · перекос" why="перекос таза не измерен" />;
  }
  // Угол линии рисуется только когда он ИЗМЕРЕН в градусах. Пересчёт из
  // миллиметров требует ширины таза, которой в протоколе нет: подставить
  // «типичную» ширину значило бы нарисовать угол, которого никто не мерил.
  const drawn = angle;
  const ray = (deg: number, len = 46) => {
    const r = (-deg * Math.PI) / 180;          // экран: y вниз, угол вправо-вверх
    return { x1: 60 - len * Math.cos(r), y1: 62 - len * Math.sin(r),
             x2: 60 + len * Math.cos(r), y2: 62 + len * Math.sin(r) };
  };

  return (
    <div className="fig">
      <div className="fig-title">{label ?? "Таз · перекос"}</div>
      <svg viewBox="0 0 120 110" role="img"
           aria-label={`Схема таза, перекос ${angle ?? "не в градусах"}`}>
        {/* Контур таза: крылья подвздошных костей и крестец. Схема, не снимок. */}
        <g fill="var(--surface-2)" stroke="var(--stroke-strong)" strokeWidth="1.2">
          <path d="M22,36 q-6,26 10,40 q14,12 20,4 q-14,-10 -12,-26 q-10,-4 -18,-18 Z" />
          <path d="M98,36 q6,26 -10,40 q-14,12 -20,4 q14,-10 12,-26 q10,-4 18,-18 Z" />
          <path d="M46,34 h28 q6,18 0,34 q-14,8 -28,0 q-6,-16 0,-34 Z" />
        </g>
        {/* Горизонталь отсчёта — то, ОТ ЧЕГО угол. Без неё угол не читается. */}
        <line x1="10" y1="62" x2="110" y2="62" stroke="var(--stroke)"
              strokeWidth="1" strokeDasharray="3 3" />
        {drawn !== null && lo !== null && hi !== null && lo !== hi && (
          <g stroke="var(--accent)" strokeWidth="1" opacity="0.28">
            {/* Веер размаха движения: от нижней границы цикла до верхней. */}
            <line {...ray(lo)} />
            <line {...ray(hi)} />
          </g>
        )}
        {drawn !== null && (
          <line {...ray(drawn)} stroke="var(--accent)" strokeWidth="2.6"
                strokeLinecap="round" />
        )}
        {drawn === null && (
          <text x="60" y="100" textAnchor="middle" className="fig-note-svg">
            только мм — угол не измерен
          </text>
        )}
      </svg>
      <Caption
        text={angle !== null ? `${fmt(angle, "°")} ${side(angle)}` : "угол не измерен"}
        sub={mm !== null ? `по таблице протокола: ${fmt(mm, "мм")} ${side(mm)}` : undefined}
      />
      {angle !== null && mm !== null && (
        <p className="fig-note">
          Две величины под одним названием: линейная разность высот (мм) и угол
          линии таза (°). Пересчёт между ними требует ширины таза — её протокол
          не печатает, поэтому оба значения хранятся раздельно.
        </p>
      )}
    </div>
  );
}

/* ── Таз, вид сверху: ротация ─────────────────────────────────────────────── */

export function PelvisAxial({ values, label }: { values: Values; label?: string }) {
  const rot = pick(values, "PELVIC_ROTATION", "DYN_PELVIC_ROTATION");
  const lo = pick(values, "DYN_PELVIC_ROTATION_ROM_MIN");
  const hi = pick(values, "DYN_PELVIC_ROTATION_ROM_MAX");
  if (rot === null) return <NoData title="Таз · ротация" why="ротация таза не измерена" />;

  const ray = (deg: number, len = 44) => {
    const r = (-deg * Math.PI) / 180;
    return { x1: 60 - len * Math.cos(r), y1: 58 - len * Math.sin(r),
             x2: 60 + len * Math.cos(r), y2: 58 + len * Math.sin(r) };
  };
  return (
    <div className="fig">
      <div className="fig-title">{label ?? "Таз · ротация"}</div>
      <svg viewBox="0 0 120 110" role="img" aria-label={`Ротация таза ${rot} градусов`}>
        <g fill="var(--surface-2)" stroke="var(--stroke-strong)" strokeWidth="1.2">
          {/* Вид сверху: два крыла и крестец между ними. */}
          <path d="M14,44 q10,-18 34,-12 q10,4 8,16 q-2,14 -16,18 q-20,4 -26,-22 Z" />
          <path d="M106,44 q-10,-18 -34,-12 q-10,4 -8,16 q2,14 16,18 q20,4 26,-22 Z" />
          <path d="M50,42 h20 q4,14 -10,22 q-14,-8 -10,-22 Z" />
        </g>
        <line x1="10" y1="58" x2="110" y2="58" stroke="var(--stroke)"
              strokeWidth="1" strokeDasharray="3 3" />
        {lo !== null && hi !== null && lo !== hi && (
          <g stroke="var(--accent-2)" strokeWidth="1" opacity="0.3">
            <line {...ray(lo)} /><line {...ray(hi)} />
          </g>
        )}
        <line {...ray(rot)} stroke="var(--accent-2)" strokeWidth="2.6" strokeLinecap="round" />
      </svg>
      <Caption
        text={`${fmt(rot, "°")} ${side(rot)}`}
        sub={lo !== null && hi !== null ? `размах ${lo}° … ${hi}°` : undefined}
      />
    </div>
  );
}

/* ── Позвоночник, фронталь: коридор отклонения вместо выдуманной кривой ───── */

export function SpineFrontal({ values, label }: { values: Values; label?: string }) {
  const rms = pick(values, "LATERAL_DEVIATION_RMS");
  const max = pick(values, "LATERAL_DEVIATION_MAX");
  const imb = pick(values, "TRUNK_IMBALANCE_VP_DM");
  const rot = pick(values, "VERTEBRAL_ROTATION_RMS");
  if (rms === null && max === null && imb === null) {
    return <NoData title="Позвоночник · фронталь" why="фронтальные параметры не измерены" />;
  }
  const SCALE = 2.2;                            // px на мм; коридор ±20 мм влезает
  const half = Math.min(30, (max ?? rms ?? 0) * SCALE);
  const shift = Math.max(-28, Math.min(28, (imb ?? 0) * SCALE));

  return (
    <div className="fig">
      <div className="fig-title">{label ?? "Позвоночник · фронталь"}</div>
      <svg viewBox="0 0 120 190" role="img" aria-label="Фронтальная схема туловища">
        {/* Силуэт спины: плечи, талия, таз. */}
        <path d="M34,26 q26,-14 52,0 q6,26 2,56 q-4,26 -2,52 q-26,12 -52,0
                 q2,-26 -2,-52 q-4,-30 2,-56 Z"
              fill="var(--surface-2)" stroke="var(--stroke-strong)" strokeWidth="1.2" />
        {/* Отвес от VP — вертикаль отсчёта. */}
        <line x1="60" y1="18" x2="60" y2="166" stroke="var(--stroke)"
              strokeWidth="1" strokeDasharray="3 3" />
        {half > 0 && (
          <rect x={60 - half} y="26" width={half * 2} height="112" rx="6"
                fill="var(--accent)" opacity="0.16" />
        )}
        {rms !== null && (
          <g stroke="var(--accent)" strokeWidth="1.4" opacity="0.75">
            <line x1={60 - rms * SCALE} y1="30" x2={60 - rms * SCALE} y2="134" />
            <line x1={60 + rms * SCALE} y1="30" x2={60 + rms * SCALE} y2="134" />
          </g>
        )}
        {/* VP и DM: измеренное смещение остистого отростка относительно ромба. */}
        <circle cx="60" cy="26" r="3.4" fill="var(--accent)" />
        <circle cx={60 + shift} cy="140" r="3.4" fill="var(--accent-2)" />
        {imb !== null && Math.abs(shift) > 0.5 && (
          <line x1="60" y1="140" x2={60 + shift} y2="140"
                stroke="var(--accent-2)" strokeWidth="2" strokeLinecap="round" />
        )}
        <text x="66" y="24" className="fig-note-svg">VP</text>
        <text x={62 + shift} y="152" className="fig-note-svg">DM</text>
      </svg>
      <Caption
        text={
          imb !== null ? `дисбаланс VP-DM ${fmt(imb, "мм")} ${side(imb)}`
          : `отклонение rms ${rms} мм`
        }
        sub={[
          rms !== null ? `rms ${rms} мм` : null,
          max !== null ? `max ${max} мм` : null,
          rot !== null ? `ротация позвонков rms ${rot}°` : null,
        ].filter(Boolean).join(" · ")}
      />
      <p className="fig-note">
        Показан коридор отклонения, а не кривая: форму линии остистых отростков
        этот протокол не выгружает. Правдоподобная кривая была бы рисунком, а не
        измерением.
      </p>
    </div>
  );
}

/* ── Позвоночник, сагитталь: дуги под измеренными углами ──────────────────── */

export function SpineSagittal({ values, label }: { values: Values; label?: string }) {
  const kyph = pick(values, "KYPHOTIC_ANGLE_ICT_ITL", "DYN_KYPHOTIC_ANGLE_ICT_ITL_MAX");
  const lord = pick(values, "LORDOTIC_ANGLE_ITL_ILS", "DYN_LORDOTIC_ANGLE_ITL_ILS_MAX");
  const sag = pick(values, "SAGITTAL_IMBALANCE_VP_DM", "DYN_SAGITTAL_IMBALANCE_VP_DM");
  if (kyph === null && lord === null) {
    return <NoData title="Позвоночник · сагитталь" why="сагиттальные углы не измерены" />;
  }
  // Дуга строится так, что угол между касательными на её концах равен
  // измеренному. Глубина сегмента: d = L/2 · tg(α/4) для дуги окружности.
  const depth = (deg: number, len: number) => (len / 2) * Math.tan((deg * Math.PI) / 720);
  const kd = kyph === null ? 0 : depth(kyph, 62);
  const ld = lord === null ? 0 : depth(lord, 54);

  return (
    <div className="fig">
      <div className="fig-title">{label ?? "Позвоночник · сагитталь"}</div>
      <svg viewBox="0 0 120 190" role="img" aria-label="Сагиттальная схема позвоночника">
        <path d="M44,20 q26,-6 34,10 q8,34 2,66 q-6,34 0,66 q-16,12 -36,4
                 q10,-32 6,-70 q-4,-40 -6,-76 Z"
              fill="var(--surface-2)" stroke="var(--stroke-strong)" strokeWidth="1.2" />
        <line x1="56" y1="18" x2="56" y2="168" stroke="var(--stroke)"
              strokeWidth="1" strokeDasharray="3 3" />
        {/* Кифоз ICT-ITL: выпуклость назад (влево на схеме — спина слева). */}
        {kyph !== null && (
          <path d={`M56,30 Q${56 - kd * 2},61 56,92`} fill="none"
                stroke="var(--accent)" strokeWidth="2.6" strokeLinecap="round" />
        )}
        {/* Лордоз ITL-ILS: выпуклость вперёд. */}
        {lord !== null && (
          <path d={`M56,92 Q${56 + ld * 2},119 56,146`} fill="none"
                stroke="var(--accent-2)" strokeWidth="2.6" strokeLinecap="round" />
        )}
        <circle cx="56" cy="30" r="3" fill="var(--text-3)" />
        <circle cx="56" cy="92" r="3" fill="var(--text-3)" />
        <circle cx="56" cy="146" r="3" fill="var(--text-3)" />
        <text x="62" y="28" className="fig-note-svg">ICT</text>
        <text x="62" y="95" className="fig-note-svg">ITL</text>
        <text x="62" y="150" className="fig-note-svg">ILS</text>
      </svg>
      <Caption
        text={[kyph !== null ? `кифоз ${kyph}°` : null, lord !== null ? `лордоз ${lord}°` : null]
          .filter(Boolean).join(" · ")}
        sub={sag !== null ? `сагиттальный дисбаланс ${fmt(sag, "°")}` : undefined}
      />
    </div>
  );
}

/* ── Стопы: распределение опоры ───────────────────────────────────────────── */

export function FeetLoad({ values, label }: { values: Values; label?: string }) {
  const l = pick(values, "LOAD_SHARE_LEFT");
  const r = pick(values, "LOAD_SHARE_RIGHT");
  const path = pick(values, "COP_PATH_LENGTH");
  const area = pick(values, "COP_AREA");
  if (l === null && r === null) return <NoData title="Стопы · опора" why="подометрия не загружена" />;

  const tone = (v: number | null) => (v === null ? 0.12 : 0.12 + 0.68 * Math.min(1, v / 60));
  return (
    <div className="fig">
      <div className="fig-title">{label ?? "Стопы · опора"}</div>
      <svg viewBox="0 0 120 110" role="img" aria-label="Распределение опоры по стопам">
        <path d="M28,16 q16,-4 20,10 q4,22 -2,44 q-2,20 -18,18 q-14,-2 -12,-22
                 q2,-32 12,-50 Z"
              fill="var(--accent)" fillOpacity={tone(l)}
              stroke="var(--stroke-strong)" strokeWidth="1.2" />
        <path d="M92,16 q-16,-4 -20,10 q-4,22 2,44 q2,20 18,18 q14,-2 12,-22
                 q-2,-32 -12,-50 Z"
              fill="var(--accent)" fillOpacity={tone(r)}
              stroke="var(--stroke-strong)" strokeWidth="1.2" />
        <text x="34" y="102" className="fig-note-svg">Л {l ?? "—"}%</text>
        <text x="74" y="102" className="fig-note-svg">П {r ?? "—"}%</text>
      </svg>
      <Caption
        text={l !== null && r !== null ? `асимметрия ${fmt(r - l, "%")}` : "доля опоры"}
        sub={[path !== null ? `путь ЦД ${path} мм` : null,
              area !== null ? `площадь ${area} мм²` : null].filter(Boolean).join(" · ")}
      />
    </div>
  );
}

/* ── Изометрическая сила: четвёртый сигнал пробы (Р-41) ───────────────────── */

export function StrengthBars({ values, label }: { values: Values; label?: string }) {
  const ext = pick(values, "MYO_FORCE_TRUNK_EXT");
  const flex = pick(values, "MYO_FORCE_TRUNK_FLEX");
  const left = pick(values, "MYO_FORCE_TRUNK_LAT_L");
  const right = pick(values, "MYO_FORCE_TRUNK_LAT_R");
  const asym = pick(values, "MYO_ASYM_TRUNK_LAT");
  if (ext === null && flex === null && left === null && right === null) {
    return <NoData title="Сила · myoline" why="myoline под этой пробой не измерялась" />;
  }
  const bars = [
    { key: "разгиб.", v: ext }, { key: "сгиб.", v: flex },
    { key: "накл. Л", v: left }, { key: "накл. П", v: right },
  ];
  // Шкала общая для всех проб: автомасштаб на карточку сделал бы соседние
  // столбцы несравнимыми, а ряд существует ровно ради сравнения (§14.2 п. 2).
  const SCALE = 500;                                   // Н на полную высоту
  const H = 74;

  return (
    <div className="fig">
      <div className="fig-title">{label ?? "Сила · myoline"}</div>
      <svg viewBox="0 0 120 110" role="img" aria-label="Изометрическая сила по группам">
        <line x1="8" y1={20 + H} x2="112" y2={20 + H} stroke="var(--stroke)" strokeWidth="1" />
        {bars.map((b, i) => {
          const x = 14 + i * 25;
          if (b.v === null) {
            return <text key={b.key} x={x + 8} y={20 + H - 4} textAnchor="middle"
                         className="fig-note-svg">—</text>;
          }
          const h = Math.max(2, Math.min(H, (b.v / SCALE) * H));
          return (
            <g key={b.key}>
              {/* Цвет нейтральный: «больше силы лучше» не установлено (Р-18). */}
              <rect x={x} y={20 + H - h} width="16" height={h} rx="4"
                    fill="var(--accent-2)" opacity="0.55" />
              <text x={x + 8} y={16 + H - h} textAnchor="middle" className="fig-note-svg">
                {Math.round(b.v)}
              </text>
              <text x={x + 8} y={20 + H + 9} textAnchor="middle" className="fig-note-svg">
                {b.key}
              </text>
            </g>
          );
        })}
      </svg>
      <Caption
        text={asym === null ? "сила по группам, Н" : `асимметрия наклона ${fmt(asym, "%")}`}
        sub={asym === null ? undefined : "положительное — правая сторона сильнее"}
      />
    </div>
  );
}

/* ── Полный ряд схем для одной пробы ──────────────────────────────────────── */

/** Порядок — §14.3: сверху вниз, как при осмотре. Схемы без данных не
 *  выбрасываются: пустое место говорит, чего в пробе не измеряли. */
export function AnatomySet({ values, label, compact = false }: {
  values: Values; label?: string; compact?: boolean;
}) {
  return (
    <div className={compact ? "fig-row compact" : "fig-row"}>
      <SpineFrontal values={values} label={label} />
      <SpineSagittal values={values} label={label} />
      <PelvisFrontal values={values} label={label} />
      <PelvisAxial values={values} label={label} />
      <FeetLoad values={values} label={label} />
      <StrengthBars values={values} label={label} />
    </div>
  );
}

const VIEWS = [
  { key: "spine_frontal", title: "Позвоночник · фронталь", C: SpineFrontal },
  { key: "spine_sagittal", title: "Позвоночник · сагитталь", C: SpineSagittal },
  { key: "pelvis_obliquity", title: "Таз · перекос", C: PelvisFrontal },
  { key: "pelvis_rotation", title: "Таз · ротация", C: PelvisAxial },
  { key: "feet", title: "Стопы · опора", C: FeetLoad },
  { key: "strength", title: "Сила · myoline", C: StrengthBars },
] as const;

/** Сопоставление проб по схемам: строка — вид, столбцы — пробы.
 *
 *  Раскладка именно такая, а не «набор схем на каждую пробу»: сравнивают
 *  ОДИН вид между пробами, и рядом должны стоять одинаковые схемы, а не
 *  разные. Число проб не ограничено — ряд прокручивается.
 */
export function AnatomyCompare({ probes }: {
  probes: { code: string; label: string; values: Values }[];
}) {
  if (probes.length === 0) return null;
  return (
    <>
      {VIEWS.map(({ key, title, C }) => (
        <div key={key}>
          <div className="section-title">{title}</div>
          <div className="fig-row compact">
            {probes.map((p) => <C key={p.code} values={p.values} label={p.label} />)}
          </div>
        </div>
      ))}
    </>
  );
}
