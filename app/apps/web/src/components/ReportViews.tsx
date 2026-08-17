/** Иллюстрации DIERS по структурам и по пробам (Р-47).
 *
 *  Иллюстрация берётся из отчёта прибора целиком — позвоночник, таз, колени,
 *  стопы. Перерисовка платформы её не заменяет: врач читает отчёт, а не
 *  пересказ. Там, где отчёт картинки не дал, так и написано; подставлять
 *  вместо неё свою схему значило бы выдать чертёж за снимок прибора.
 *
 *  Структура берётся из ПЕЧАТНОГО ЗАГОЛОВКА страницы, а не из пикселей: прибор
 *  сам называет, о чём лист. Если лист говорит сразу о нескольких структурах —
 *  так и сказано, а иллюстрация показана в каждом из названных разделов.
 */
import { useState } from "react";
import type { FigureOut } from "../lib/api";
import { Card, Empty } from "./ui";
import { groupFigures } from "./ProtocolFigures";

export const STRUCTURE_RU: Record<string, string> = {
  spine: "Позвоночник",
  pelvis: "Таз",
  knee: "Колени и ось ног",
  feet: "Стопы и опора",
};
export const STRUCTURE_ORDER = ["spine", "pelvis", "knee", "feet"];

const forStructure = (figures: FigureOut[], structure: string) =>
  figures.filter((f) => (f.structures ?? []).includes(structure));

function Plate({ figures, onOpen }: { figures: FigureOut[]; onOpen: (f: FigureOut) => void }) {
  const { groups, orphans } = groupFigures(figures);
  if (groups.length === 0 && orphans.length === 0) return null;
  return (
    <div className="report-grid">
      {groups.map(({ render, captions }) => (
        <figure key={render.id} className="report-fig">
          <button className="report-image" onClick={() => onOpen(render)}
                  title={`${render.name} · стр. ${render.page + 1} · открыть крупно`}>
            <img src={render.data_uri ?? render.url}
                 alt={`Иллюстрация отчёта ${render.name}`} loading="lazy" />
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
  );
}

/** Одна проба: иллюстрации отчёта, разложенные по структурам. */
export function ReportByStructure({ figures, probe }: { figures: FigureOut[]; probe?: string }) {
  const [open, setOpen] = useState<FigureOut | null>(null);
  const mine = probe ? figures.filter((f) => f.probe_code === probe) : figures;
  const unclassified = mine.filter((f) => (f.structures ?? []).length === 0);

  return (
    <>
      {STRUCTURE_ORDER.map((key) => {
        const list = forStructure(mine, key);
        return (
          <div key={key}>
            <div className="section-title">{STRUCTURE_RU[key]} · из отчёта DIERS</div>
            <Card>
              {list.length === 0 ? (
                <Empty text={
                  "В загруженных страницах отчёта иллюстрации этой структуры нет. "
                  + "Загрузите соответствующие листы — они разложатся сюда сами."
                } />
              ) : (
                <>
                  <Plate figures={list} onOpen={setOpen} />
                  {list.some((f) => (f.structures ?? []).length > 1) && (
                    <p className="tile-hint">
                      Лист отчёта называет несколько структур сразу, поэтому его
                      иллюстрации показаны в каждом из названных разделов.
                    </p>
                  )}
                </>
              )}
            </Card>
          </div>
        );
      })}

      {unclassified.length > 0 && (
        <>
          <div className="section-title">Прочие иллюстрации отчёта</div>
          <Card>
            <p className="tile-hint" style={{ marginTop: 0 }}>
              Страница не назвала структуру печатным заголовком. Раскладывать по
              разделам по виду картинки платформа не станет: это была бы догадка,
              неотличимая в отчёте от факта.
            </p>
            <Plate figures={unclassified} onOpen={setOpen} />
          </Card>
        </>
      )}

      {open && (
        <div className="fig-modal" role="dialog" aria-modal="true" onClick={() => setOpen(null)}>
          <img src={open.data_uri ?? open.url} alt={`Иллюстрация отчёта ${open.name}`} />
          <button className="pill" onClick={() => setOpen(null)}>Закрыть</button>
        </div>
      )}
    </>
  );
}

/** Сравнение проб по иллюстрациям отчёта: строка — структура, столбцы — пробы. */
export function ReportCompare({ figures, probes, orientation = "rows" }: {
  figures: FigureOut[];
  probes: { code: string; label: string }[];
  orientation?: "rows" | "columns";
}) {
  const [open, setOpen] = useState<FigureOut | null>(null);
  if (probes.length === 0) return null;

  const cell = (structure: string, probe: string) => {
    const list = forStructure(figures.filter((f) => f.probe_code === probe), structure);
    if (list.length === 0) {
      return <div className="report-cell empty">нет листа в отчёте</div>;
    }
    return <div className="report-cell"><Plate figures={list} onOpen={setOpen} /></div>;
  };

  const body = orientation === "columns" ? (
    <div className="fig-columns">
      {probes.map((p) => (
        <div key={p.code} className="fig-column report-column">
          <div className="fig-column-head">{p.label}</div>
          {STRUCTURE_ORDER.map((s) => (
            <div key={s}>
              <div className="fig-column-view">{STRUCTURE_RU[s]}</div>
              {cell(s, p.code)}
            </div>
          ))}
        </div>
      ))}
    </div>
  ) : (
    <>
      {STRUCTURE_ORDER.map((s) => (
        <div key={s}>
          <div className="section-title">{STRUCTURE_RU[s]} · из отчёта DIERS</div>
          <div className="fig-columns">
            {probes.map((p) => (
              <div key={p.code} className="fig-column report-column">
                <div className="fig-column-head">{p.label}</div>
                {cell(s, p.code)}
              </div>
            ))}
          </div>
        </div>
      ))}
    </>
  );

  return (
    <>
      {body}
      {open && (
        <div className="fig-modal" role="dialog" aria-modal="true" onClick={() => setOpen(null)}>
          <img src={open.data_uri ?? open.url} alt={`Иллюстрация отчёта ${open.name}`} />
          <button className="pill" onClick={() => setOpen(null)}>Закрыть</button>
        </div>
      )}
    </>
  );
}
