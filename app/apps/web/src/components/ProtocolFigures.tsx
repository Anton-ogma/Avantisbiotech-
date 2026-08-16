/** Иллюстрации из печатного протокола прибора, как они есть (Р-40).
 *
 *  Рядом со схемами, построенными из измерений, а не вместо них. Разница
 *  существенна: печатная иллюстрация — свидетельство того, что прибор показал
 *  оператору в тот день, и на ней встречаются величины, которых нет в
 *  текстовом слое и, значит, нет в разборе. Именно поэтому она хранится, а не
 *  выбрасывается: расхождение таблицы со схемой видно только при обеих.
 */
import { useState } from "react";
import type { FigureOut } from "../lib/api";

export function ProtocolFigures({ figures, probe }: { figures: FigureOut[]; probe?: string }) {
  const [open, setOpen] = useState<FigureOut | null>(null);
  const shown = probe ? figures.filter((f) => f.probe_code === probe) : figures;
  if (shown.length === 0) return null;

  const renders = shown.filter((f) => f.kind === "render");
  const captions = shown.filter((f) => f.kind === "caption");

  return (
    <>
      <div className="fig-strip">
        {renders.map((f) => (
          <button key={f.id} className="fig-thumb" onClick={() => setOpen(f)}
                  title={`${f.name} · ${f.width}×${f.height}`}>
            <img src={f.data_uri ?? f.url} alt={`Иллюстрация протокола ${f.name}`}
                 loading="lazy" />
          </button>
        ))}
      </div>
      {captions.length > 0 && (
        <>
          <p className="tile-hint" style={{ marginBottom: 6 }}>
            Подписи на иллюстрациях напечатаны растром: это изображение, а не
            данные. Разбор их не читает — значения с них вводятся вручную и
            хранятся с отдельным источником.
          </p>
          <div className="fig-strip captions">
            {captions.map((f) => (
              <img key={f.id} src={f.data_uri ?? f.url} alt={`Подпись протокола ${f.name}`}
                   loading="lazy" />
            ))}
          </div>
        </>
      )}
      {open && (
        <div className="fig-modal" role="dialog" aria-modal="true"
             onClick={() => setOpen(null)}>
          <img src={open.data_uri ?? open.url} alt={`Иллюстрация протокола ${open.name}`} />
          <button className="pill" onClick={() => setOpen(null)}>Закрыть</button>
        </div>
      )}
    </>
  );
}
