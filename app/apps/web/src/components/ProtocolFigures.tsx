/** Иллюстрации протокола прибора — как они напечатаны (Р-40, Р-46).
 *
 *  Это ГЛАВНОЕ изображение пробы, когда протокол его дал. Собственные схемы
 *  платформы существуют для другого: сравнить четыре пробы между собой по
 *  одному виду. Подменять ими печатную иллюстрацию нельзя — врач читает
 *  отчёт прибора, а не пересказ.
 *
 *  Группировка воспроизводит раскладку листа: изображение и следующие за ним
 *  подписи-растры принадлежат одному виду. Порядок берётся из самого PDF —
 *  сначала схема, потом её напечатанные значения, — и другого способа связать
 *  подпись со схемой нет: координат у растра в текстовом слое не бывает.
 */
import { useState } from "react";
import type { FigureOut } from "../lib/api";

type Group = { render: FigureOut; captions: FigureOut[] };

/** Схема забирает подписи, идущие за ней до следующей схемы. */
export function groupFigures(figures: FigureOut[]): { groups: Group[]; orphans: FigureOut[] } {
  const groups: Group[] = [];
  const orphans: FigureOut[] = [];
  for (const f of figures) {
    if (f.kind === "render") groups.push({ render: f, captions: [] });
    else if (groups.length) groups[groups.length - 1].captions.push(f);
    else orphans.push(f);          // подписи раньше первой схемы: чьи — неизвестно
  }
  return { groups, orphans };
}

export function ProtocolFigures({ figures, probe }: { figures: FigureOut[]; probe?: string }) {
  const [open, setOpen] = useState<FigureOut | null>(null);
  const shown = probe ? figures.filter((f) => f.probe_code === probe) : figures;
  if (shown.length === 0) return null;
  const { groups, orphans } = groupFigures(shown);

  return (
    <>
      <div className="report-grid">
        {groups.map(({ render, captions }) => (
          <figure key={render.id} className="report-fig">
            <button className="report-image" onClick={() => setOpen(render)}
                    title={`${render.name} · ${render.width}×${render.height} · открыть крупно`}>
              <img src={render.data_uri ?? render.url}
                   alt={`Иллюстрация протокола ${render.name}`} loading="lazy" />
            </button>
            {captions.length > 0 && (
              <figcaption className="report-captions">
                {captions.map((c) => (
                  <img key={c.id} src={c.data_uri ?? c.url}
                       alt={`Напечатанное значение ${c.name}`} loading="lazy" />
                ))}
              </figcaption>
            )}
          </figure>
        ))}
      </div>

      {orphans.length > 0 && (
        <div className="report-captions" style={{ marginTop: 8 }}>
          {orphans.map((c) => (
            <img key={c.id} src={c.data_uri ?? c.url}
                 alt={`Напечатанное значение ${c.name}`} loading="lazy" />
          ))}
        </div>
      )}

      <p className="tile-hint">
        Значения на иллюстрациях напечатаны растром — это изображение, а не
        данные: разбор их не читает, и они введены вручную с отдельным
        источником. Числа здесь — те же, что на бумаге.
      </p>

      {open && (
        <div className="fig-modal" role="dialog" aria-modal="true" onClick={() => setOpen(null)}>
          <img src={open.data_uri ?? open.url} alt={`Иллюстрация протокола ${open.name}`} />
          <button className="pill" onClick={() => setOpen(null)}>Закрыть</button>
        </div>
      )}
    </>
  );
}
