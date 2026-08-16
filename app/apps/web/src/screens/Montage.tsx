/** Монтаж ЭМГ: шаблоны групп мышц и ручная пропись каналов (Р-42).
 *
 *  Экран отвечает на вопрос, который платформа сама решить не может: какой
 *  провод к какой мышце приклеен. Миограф подписывает каналы «CH1…CH8», и без
 *  прописи такой столбец не опознаётся ничем — угадывать платформа не вправе.
 *
 *  Шаблон здесь — заготовка, а не предписание: он разворачивается в список
 *  каналов, который оператор правит. Правится и метка (как подписан провод),
 *  и состав.
 */
import { useEffect, useMemo, useState } from "react";
import {
  api, isSnapshot,
  type MontageOut, type MontageTemplate, type MuscleInfo, type SessionOut,
} from "../lib/api";
import { Banner, Card, Empty, Tile } from "../components/ui";

type Row = { label: string; muscle: string; side: "L" | "R" };

const REGION_RU: Record<string, string> = {
  masticatory: "Жевательные", neck: "Шея", shoulder: "Плечевой пояс",
  spine_frontal: "Позвоночник · фронталь", spine_sagittal: "Спина",
  abdomen: "Живот", pelvis: "Таз", thigh: "Бедро", shank: "Голень и стопа",
  leg_axis: "Ось ног", feet: "Стопы",
};

export function Montage({ sessions }: { sessions: SessionOut[] }) {
  const [selected, setSelected] = useState(sessions[0]?.id ?? "");
  const [muscles, setMuscles] = useState<MuscleInfo[]>([]);
  const [templates, setTemplates] = useState<MontageTemplate[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [note, setNote] = useState("");
  const [template, setTemplate] = useState<string | null>(null);
  const [current, setCurrent] = useState<MontageOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const offline = isSnapshot();

  useEffect(() => {
    Promise.all([api.muscles(), api.montageTemplates()])
      .then(([m, t]) => { setMuscles(m.muscles); setTemplates(t.montages); })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setSaved(null);
    api.sessionMontage(selected)
      .then((m) => {
        setCurrent(m.montage);
        setRows((m.montage?.channels ?? []).map((c) => ({
          label: c.label, muscle: c.muscle, side: c.side as "L" | "R",
        })));
        setTemplate(m.montage?.template ?? null);
        setNote(m.montage?.note ?? "");
      })
      .catch((e) => setError(e.message));
  }, [selected]);

  /** Поверхностно недоступные мышцы показываются, но выбрать их нельзя:
   *  скрыть — значит оставить оператора гадать, почему её нет в списке. */
  const selectable = useMemo(() => muscles.filter((m) => m.surface), [muscles]);
  const deep = useMemo(() => muscles.filter((m) => !m.surface), [muscles]);

  const byRegion = useMemo(() => {
    const out = new Map<string, MuscleInfo[]>();
    for (const m of selectable) {
      const list = out.get(m.region) ?? [];
      list.push(m);
      out.set(m.region, list);
    }
    return [...out.entries()];
  }, [selectable]);

  function applyTemplate(code: string) {
    const t = templates.find((x) => x.code === code);
    if (!t) return;
    setTemplate(code);
    setRows(t.channels.map((c) => ({ label: c.label, muscle: c.muscle, side: c.side as "L" | "R" })));
    setSaved(null);
  }

  const addRow = () =>
    setRows((r) => [...r, { label: `CH${r.length + 1}`, muscle: selectable[0]?.code ?? "", side: "L" }]);
  const patch = (i: number, p: Partial<Row>) =>
    setRows((r) => r.map((row, j) => (j === i ? { ...row, ...p } : row)));
  const drop = (i: number) => setRows((r) => r.filter((_, j) => j !== i));

  // Дубли ловятся здесь же: при разборе одна запись перетёрла бы другую, и
  // узнать об этом на экране настройки лучше, чем по пропавшей колонке.
  const duplicates = useMemo(() => {
    const seen = new Map<string, number>();
    const bad = new Set<number>();
    rows.forEach((r, i) => {
      const key = r.label.trim().toLowerCase().replace(/[-_\s]+/g, " ");
      if (!key) return;
      if (seen.has(key)) { bad.add(i); bad.add(seen.get(key)!); }
      else seen.set(key, i);
    });
    return bad;
  }, [rows]);

  const oneSided = useMemo(() => {
    const sides = new Map<string, Set<string>>();
    for (const r of rows) {
      if (!sides.has(r.muscle)) sides.set(r.muscle, new Set());
      sides.get(r.muscle)!.add(r.side);
    }
    return [...sides.entries()].filter(([, s]) => s.size < 2).map(([m]) => m);
  }, [rows]);

  async function save() {
    setError(null); setSaved(null);
    try {
      const out = await api.setMontage(selected, { template, channels: rows, note });
      setCurrent(out.montage);
      setSaved(`Монтаж сохранён: ${out.montage.channels.length} каналов`
        + (out.warnings?.length ? ` · ${out.warnings.join("; ")}` : ""));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const ru = (code: string) => muscles.find((m) => m.code === code)?.label_ru ?? code;

  return (
    <>
      <h1 className="title">Монтаж ЭМГ</h1>
      <p className="subtitle">
        Какой канал к какой мышце приклеен. Миограф подписывает провода по-своему —
        «CH1», «EMG 3», — и по имени столбца мышцу не восстановить. Шаблон даёт
        типовую раскладку группы, дальше правится вручную: и метка, и состав.
      </p>
      {offline && (
        <Banner text={
          "Открыт автономный снимок: монтаж показывается, но сохранить его некуда — " +
          "бэкенда рядом нет."
        } />
      )}
      {error && <Banner text={error} />}

      <Card>
        <div className="row">
          <span className="tile-label">Сессия</span>
          <select className="pill" style={{ minWidth: 300 }} value={selected}
                  onChange={(e) => setSelected(e.target.value)}>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {new Date(s.started_at).toLocaleDateString("ru-RU")} · {s.patient_ref.slice(0, 22)}
              </option>
            ))}
          </select>
          {current
            ? <span className="badge good">задан · {current.channels.length} каналов</span>
            : <span className="badge">монтаж не задан</span>}
        </div>
      </Card>

      <div className="section-title">Шаблоны групп мышц</div>
      <div className="grid cols-3">
        {templates.map((t) => (
          <button key={t.code} className="list-row" style={{ textAlign: "left" }}
                  aria-pressed={template === t.code} onClick={() => applyTemplate(t.code)}>
            <div>
              <strong>{t.label_ru}</strong>
              <div className="tile-hint">{t.purpose}</div>
              <div className="mono">{t.channel_count} каналов</div>
            </div>
          </button>
        ))}
      </div>

      <div className="section-title">Каналы записи</div>
      <Card>
        {rows.length === 0 ? (
          <Empty text="Каналов нет. Возьмите шаблон выше или добавьте вручную." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Метка на миографе</th><th>Мышца</th><th>Сторона</th>
                  <th>Код параметра</th><th />
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className={duplicates.has(i) ? "row-bad" : undefined}>
                    <td>
                      <input className="pill" style={{ width: 140 }} value={r.label}
                             aria-label={`метка канала ${i + 1}`}
                             onChange={(e) => patch(i, { label: e.target.value })} />
                    </td>
                    <td>
                      <select className="pill" style={{ minWidth: 220 }} value={r.muscle}
                              onChange={(e) => patch(i, { muscle: e.target.value })}>
                        {byRegion.map(([region, list]) => (
                          <optgroup key={region} label={REGION_RU[region] ?? region}>
                            {list.map((m) => (
                              <option key={m.code} value={m.code}>{m.label_ru}</option>
                            ))}
                          </optgroup>
                        ))}
                      </select>
                    </td>
                    <td>
                      <select className="pill" value={r.side}
                              onChange={(e) => patch(i, { side: e.target.value as "L" | "R" })}>
                        <option value="L">слева</option>
                        <option value="R">справа</option>
                      </select>
                    </td>
                    <td className="mono">EMG_RMS_{r.muscle}_{r.side}</td>
                    <td>
                      <button className="pill" onClick={() => drop(i)}
                              aria-label={`убрать канал ${r.label}`}>убрать</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="row" style={{ marginTop: 14 }}>
          <button className="pill" onClick={addRow}>+ канал</button>
          <input className="pill" style={{ flex: 1, minWidth: 200 }} value={note}
                 placeholder="примечание: расстановка электродов, дата записи"
                 onChange={(e) => setNote(e.target.value)} />
          <button className="pill primary" onClick={save}
                  disabled={offline || rows.length === 0 || duplicates.size > 0}>
            Сохранить монтаж
          </button>
        </div>

        {duplicates.size > 0 && (
          <p className="tile-hint">
            Одна метка назначена дважды: при разборе вторая запись перетёрла бы
            первую. Исправьте метки — сохранение заблокировано.
          </p>
        )}
        {oneSided.length > 0 && duplicates.size === 0 && (
          <p className="tile-hint">
            Записаны с одной стороны, асимметрия по ним считаться не будет:{" "}
            {oneSided.map(ru).join(", ")}.
          </p>
        )}
        {saved && <p className="tile-hint"><strong>{saved}</strong></p>}
      </Card>

      {rows.length > 0 && (
        <div className="grid cols-3">
          <Tile label="Каналов" value={rows.length} hint="физических отводов" />
          <Tile label="Мышц" value={new Set(rows.map((r) => r.muscle)).size}
                hint="считая обе стороны за одну" />
          <Tile label="Асимметрий" value={new Set(rows.map((r) => r.muscle)).size - oneSided.length}
                hint="считаются только для мышц с обеими сторонами" />
        </div>
      )}

      {deep.length > 0 && (
        <>
          <div className="section-title">Недоступны поверхностной ЭМГ</div>
          <Card>
            <p className="tile-hint" style={{ marginTop: 0 }}>
              Эти мышцы в каталоге есть, но подписать ими канал нельзя: электрод
              снимет с них не их. Список показан намеренно — иначе оператор
              искал бы пропавшую мышцу в выпадающем списке.
            </p>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Мышца</th><th>Латинское название</th><th>Почему</th></tr></thead>
                <tbody>
                  {deep.map((m) => (
                    <tr key={m.code}>
                      <td>{m.label_ru}<div className="mono">{m.code}</div></td>
                      <td className="muted">{m.latin}</td>
                      <td className="tile-hint">{m.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </>
  );
}
