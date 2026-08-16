import type { CSSProperties, ReactNode } from "react";
import type { Confidence, Direction } from "../lib/api";

export const Card = ({ children, style }: { children: ReactNode; style?: CSSProperties }) => (
  <div className="card fade-in" style={style}>{children}</div>
);

export const Tile = ({ label, value, hint, tone }: {
  label: string; value: ReactNode; hint?: string; tone?: "good" | "bad" | "neutral" | "warn";
}) => (
  <div className="card fade-in">
    <div className="tile-label">{label}</div>
    <div className="tile-value" style={tone ? { color: `var(--${tone})` } : undefined}>{value}</div>
    {hint && <div className="tile-hint">{hint}</div>}
  </div>
);

export const Banner = ({ text }: { text: string }) => (
  <div className="banner" role="status">
    <span className="banner-icon" aria-hidden>⚠</span>
    <span>{text}</span>
  </div>
);

/** MUST §14.2.3: цвет кодирует направление ТОЛЬКО когда оно известно.
 *  Параметр с direction=unknown всегда нейтральный — предрешать результат
 *  окраской нельзя (Р-18). Цвет не единственный носитель смысла: рядом
 *  всегда стоит текстовая метка (§14 A11y). */
export function DeltaBadge({ delta, confidence, interpretation, direction, unit }: {
  delta: number; confidence: Confidence;
  interpretation: "improving" | "worsening" | null; direction: Direction; unit?: string;
}) {
  const inNoise = confidence === "noise" || confidence === "undefined";
  const tone = inNoise || interpretation === null ? "neutral"
    : interpretation === "improving" ? "good" : "bad";
  const label = inNoise ? "в шуме"
    : interpretation === "improving" ? "улучшение"
    : interpretation === "worsening" ? "ухудшение"
    : direction === "unknown" ? "направление не установлено" : "изменение";
  return (
    <span className={`badge ${tone}`} title={label}>
      <span aria-hidden>{delta > 0 ? "▲" : delta < 0 ? "▼" : "—"}</span>
      {delta > 0 ? "+" : ""}{delta.toFixed(2)}{unit ? ` ${unit}` : ""}
      <span className="muted" style={{ fontWeight: 500 }}>· {label}</span>
    </span>
  );
}

export function Segmented<T extends string>({ value, options, onChange }: {
  value: T; options: { value: T; label: string }[]; onChange: (v: T) => void;
}) {
  return (
    <div className="segmented" role="tablist">
      {options.map((o) => (
        <button key={o.value} role="tab" aria-pressed={value === o.value}
                onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export const Empty = ({ text }: { text: string }) => <div className="empty">{text}</div>;
