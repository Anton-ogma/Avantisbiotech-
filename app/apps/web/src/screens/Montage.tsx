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
  type BleCaptureOut, type BleProfile, type MontageOut, type MontageTemplate,
  type MuscleInfo, type SessionOut,
} from "../lib/api";
import { BleCapture } from "../components/BleCapture";
import { Banner, Card, Empty, Tile } from "../components/ui";

type Row = { label: string; muscle: string; side: "L" | "R" };

const REGION_RU: Record<string, string> = {
  masticatory: "Жевательные", neck: "Шея", shoulder: "Плечевой пояс",
  spine_frontal: "Позвоночник · фронталь", spine_sagittal: "Спина",
  abdomen: "Живот", pelvis: "Таз", thigh: "Бедро", shank: "Голень и стопа",
  leg_axis: "Ось ног", feet: "Стопы",
};

export function Montage({ sessions }: { sessions: SessionOut[] }) {
  // Сессии приходят асинхронно: на первом рендере список ПУСТ, и значение по
  // умолчанию, снятое с него один раз, так и остаётся "". Экран при этом
  // выглядит рабочим — в select нарисован первый вариант, — а сохранение уходит
  // по адресу `/sessions//montage` и молча не доезжает. Синхронизация ниже.
  const [selected, setSelected] = useState("");
  const [muscles, setMuscles] = useState<MuscleInfo[]>([]);
  const [templates, setTemplates] = useState<MontageTemplate[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [note, setNote] = useState("");
  const [template, setTemplate] = useState<string | null>(null);
  const [current, setCurrent] = useState<MontageOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  // Свой шаблон: набор «мышца + стороны», а не готовых каналов. Метки провода
  // на этом уровне не задаются — они у каждой записи свои.
  const [building, setBuilding] = useState(false);
  const [tplCode, setTplCode] = useState("");
  const [tplLabel, setTplLabel] = useState("");
  const [tplPurpose, setTplPurpose] = useState("");
  const [tplGroups, setTplGroups] = useState<{ muscle: string; side: string }[]>([]);
  const [profiles, setProfiles] = useState<BleProfile[]>([]);
  const [trials, setTrials] = useState<{ id: string; label: string }[]>([]);
  const [captureTrial, setCaptureTrial] = useState("");
  const [captured, setCaptured] = useState<BleCaptureOut | null>(null);
  const offline = isSnapshot();

  useEffect(() => {
    if (sessions.length === 0) return;
    if (!selected || !sessions.some((s) => s.id === selected)) setSelected(sessions[0].id);
  }, [sessions, selected]);

  useEffect(() => {
    Promise.all([api.muscles(), api.montageTemplates()])
      .then(([m, t]) => { setMuscles(m.muscles); setTemplates(t.montages); })
      .catch((e) => setError(e.message));
    // Профили датчиков — конфигурация; отсутствие их не ломает экран монтажа.
    api.bleProfiles().then((p) => setProfiles(p.profiles)).catch(() => setProfiles([]));
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
    setCaptured(null);
    api.measurements(selected)
      .then((m) => {
        const list = m.trials.map((x) => ({ id: x.trial_id, label: x.label_ru }));
        setTrials(list);
        setCaptureTrial(list[0]?.id ?? "");
      })
      .catch(() => setTrials([]));
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

  /** Новый канал берёт первую СВОБОДНУЮ пару «мышца + сторона»: строка,
   *  конфликтующая с уже набранной в момент своего появления, блокировала бы
   *  сохранение сразу после нажатия «+ канал». */
  const addRow = () =>
    setRows((r) => {
      const taken = new Set(r.map((x) => `${x.muscle}|${x.side}`));
      const free = selectable.flatMap((m) => (["L", "R"] as const).map((s) => ({ muscle: m.code, side: s })))
        .find((c) => !taken.has(`${c.muscle}|${c.side}`));
      const labels = new Set(r.map((x) => x.label.trim().toLowerCase()));
      let n = r.length + 1;
      while (labels.has(`ch${n}`)) n += 1;
      return [...r, {
        label: `CH${n}`,
        muscle: free?.muscle ?? selectable[0]?.code ?? "",
        side: free?.side ?? "L",
      }];
    });
  const patch = (i: number, p: Partial<Row>) =>
    setRows((r) => r.map((row, j) => (j === i ? { ...row, ...p } : row)));
  const drop = (i: number) => setRows((r) => r.filter((_, j) => j !== i));

  // Дубли ловятся здесь же: при разборе одна запись перетёрла бы другую, и
  // узнать об этом на экране настройки лучше, чем по пропавшей колонке.
  //
  // Дублей ДВА вида, и оба кончаются потерей канала. Одинаковая метка провода —
  // разбор не различит столбцы. Одинаковая пара «мышца + сторона» под разными
  // метками — параметр EMG_RMS_<мышца>_<сторона> один, и вторая запись затрёт
  // первую. Сервер отвергает оба (domain/montage.py), но узнавать об этом по
  // ошибке сохранения — значит потерять уже набранный монтаж из виду.
  const conflicts = useMemo(() => {
    const byLabel = new Map<string, number>();
    const bySite = new Map<string, number>();
    const bad = new Set<number>();
    const sameLabel: string[] = [];
    const sameSite: string[] = [];
    rows.forEach((r, i) => {
      const key = r.label.trim().toLowerCase().replace(/[-_\s]+/g, " ");
      if (key) {
        if (byLabel.has(key)) { bad.add(i); bad.add(byLabel.get(key)!); sameLabel.push(r.label.trim()); }
        else byLabel.set(key, i);
      }
      if (!r.muscle) return;
      const site = `${r.muscle}|${r.side}`;
      if (bySite.has(site)) { bad.add(i); bad.add(bySite.get(site)!); sameSite.push(site); }
      else bySite.set(site, i);
    });
    return { rows: bad, sameLabel, sameSite };
  }, [rows]);
  const duplicates = conflicts.rows;

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

  const inTemplate = (code: string) => tplGroups.some((g) => g.muscle === code);
  const toggleMuscle = (code: string) =>
    setTplGroups((g) => inTemplate(code)
      ? g.filter((x) => x.muscle !== code)
      : [...g, { muscle: code, side: "both" }]);
  const setSide = (code: string, side: string) =>
    setTplGroups((g) => g.map((x) => (x.muscle === code ? { ...x, side } : x)));
  const addRegion = (region: string) =>
    setTplGroups((g) => {
      const add = selectable.filter((m) => m.region === region && !g.some((x) => x.muscle === m.code));
      return [...g, ...add.map((m) => ({ muscle: m.code, side: "both" }))];
    });

  async function saveTemplate() {
    setError(null); setSaved(null);
    try {
      const out = await api.saveTemplate({
        code: tplCode.trim(), label_ru: tplLabel.trim(),
        purpose: tplPurpose.trim(), channels: tplGroups,
      });
      setTemplates((prev) => [...prev.filter((x) => x.code !== out.template.code), out.template]);
      setSaved(`Шаблон «${out.template.label_ru}» сохранён: ${out.template.channel_count} каналов`
        + (out.warnings?.length ? ` · ${out.warnings.join("; ")}` : ""));
      setBuilding(false); setTplGroups([]); setTplCode(""); setTplLabel("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function archive(code: string) {
    setError(null);
    try {
      await api.archiveTemplate(code);
      setTemplates((prev) => prev.filter((x) => x.code !== code));
      setSaved(`Шаблон ${code} убран из списка; записанные по нему сессии не тронуты`);
    } catch (e) {
      setError((e as Error).message);
    }
  }

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

      <div className="row" style={{ marginTop: 26, marginBottom: 12 }}>
        <div className="section-title" style={{ margin: 0 }}>Шаблоны групп мышц</div>
        <span className="spacer" />
        <button className="pill" aria-pressed={building} onClick={() => setBuilding((b) => !b)}>
          {building ? "Свернуть" : "+ свой шаблон"}
        </button>
      </div>
      <div className="grid cols-3">
        {templates.map((t) => (
          <div key={t.code} className="list-row" style={{ textAlign: "left" }}>
            <button style={{ all: "unset", cursor: "pointer", flex: 1 }}
                    aria-pressed={template === t.code} onClick={() => applyTemplate(t.code)}>
              <strong>{t.label_ru}</strong>
              {t.builtin === false && <span className="badge accent" style={{ marginLeft: 8 }}>свой</span>}
              <div className="tile-hint">{t.purpose}</div>
              <div className="mono">{t.channel_count} каналов · {t.code}</div>
            </button>
            {t.builtin === false && (
              <button className="pill" disabled={offline} onClick={() => archive(t.code)}
                      aria-label={`убрать шаблон ${t.label_ru}`}>убрать</button>
            )}
          </div>
        ))}
      </div>

      {building && (
        <Card>
          <div className="tile-label" style={{ marginBottom: 10 }}>
            Свой шаблон · выбрано мышц: {tplGroups.length}
          </div>
          <div className="row" style={{ marginBottom: 12 }}>
            <input className="pill" style={{ width: 180 }} value={tplCode}
                   placeholder="код: MY_PANEL"
                   onChange={(e) => setTplCode(e.target.value.toUpperCase())} />
            <input className="pill" style={{ width: 240 }} value={tplLabel}
                   placeholder="название по-русски"
                   onChange={(e) => setTplLabel(e.target.value)} />
            <input className="pill" style={{ flex: 1, minWidth: 200 }} value={tplPurpose}
                   placeholder="для какой пробы"
                   onChange={(e) => setTplPurpose(e.target.value)} />
          </div>

          {byRegion.map(([region, list]) => (
            <div key={region} style={{ marginBottom: 12 }}>
              <div className="row">
                <span className="tile-label">{REGION_RU[region] ?? region}</span>
                <button className="pill" onClick={() => addRegion(region)}>
                  + вся группа
                </button>
              </div>
              <div className="row" style={{ marginTop: 6 }}>
                {list.map((m) => {
                  const on = inTemplate(m.code);
                  const side = tplGroups.find((g) => g.muscle === m.code)?.side ?? "both";
                  return (
                    <span key={m.code} className="row" style={{ gap: 4 }}>
                      <button className="pill" aria-pressed={on}
                              onClick={() => toggleMuscle(m.code)} title={m.latin}>
                        {on ? "− " : "+ "}{m.label_ru}
                      </button>
                      {on && (
                        <select className="pill" value={side}
                                aria-label={`стороны для ${m.label_ru}`}
                                onChange={(e) => setSide(m.code, e.target.value)}>
                          <option value="both">обе</option>
                          <option value="L">только слева</option>
                          <option value="R">только справа</option>
                        </select>
                      )}
                    </span>
                  );
                })}
              </div>
            </div>
          ))}

          <div className="row" style={{ marginTop: 8 }}>
            <span className="tile-hint" style={{ flex: 1 }}>
              «Обе» даёт два отвода и асимметрию. Односторонний выбор законен —
              так пишут, когда интересует сторона поражения, — но асимметрии по
              такой мышце не будет.
            </span>
            <button className="pill primary" disabled={
              offline || tplGroups.length === 0 || tplCode.trim().length < 2
              || tplLabel.trim().length === 0
            } onClick={saveTemplate}>
              Сохранить шаблон
            </button>
          </div>
        </Card>
      )}

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
            {conflicts.sameLabel.length > 0 && (
              <>Одна метка назначена дважды ({[...new Set(conflicts.sameLabel)].join(", ")}):
                при разборе вторая запись перетёрла бы первую.{" "}</>
            )}
            {conflicts.sameSite.length > 0 && (
              <>Одна и та же мышца со стороной записана дважды под разными метками
                ({[...new Set(conflicts.sameSite)].map((s) => {
                  const [m, side] = s.split("|");
                  return `${ru(m)} ${side}`;
                }).join(", ")}): показатель EMG_RMS у них один, и второй отвод
                затёр бы первый.{" "}</>
            )}
            Сохранение заблокировано.
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

      {profiles.length > 0 && (
        <>
          <div className="section-title">Запись с беспроводных датчиков</div>
          <div className="row" style={{ marginBottom: 10 }}>
            <span className="tile-label">Проба</span>
            <select className="pill" style={{ minWidth: 260 }} value={captureTrial}
                    onChange={(e) => setCaptureTrial(e.target.value)}>
              {trials.map((tr) => <option key={tr.id} value={tr.id}>{tr.label}</option>)}
            </select>
            {rows.length === 0 && (
              <span className="badge">монтаж не задан — каналы уйдут без прописи</span>
            )}
          </div>
          <BleCapture
            profiles={profiles}
            disabled={offline || !captureTrial}
            onCapture={async (payload) => {
              const out = await api.bleCapture(selected, { ...payload, trial_id: captureTrial });
              setCaptured(out);
            }}
          />
          {captured && (
            <Card>
              <div className="row">
                <span className={`badge ${captured.status === "captured" ? "good" : ""}`}>
                  {captured.status === "captured" ? "записано" : captured.status}
                </span>
                {captured.fs_actual != null && (
                  <span className="badge">
                    частота факт. {captured.fs_actual} Гц из {captured.fs_declared}
                  </span>
                )}
                {captured.duration_sec != null && (
                  <span className="badge">{captured.duration_sec} с</span>
                )}
              </div>
              {(captured.channels ?? []).length > 0 && (
                <div className="table-wrap" style={{ marginTop: 12 }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Канал</th><th className="num">RMS, мкВ</th>
                        <th className="num">пик</th><th className="num">SNR, дБ</th>
                        <th className="num">выброшено, дБ</th><th>Флаги</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(captured.channels ?? []).map((c) => (
                        <tr key={c.label}>
                          <td>{c.label}</td>
                          <td className="num">{c.rms_uv}</td>
                          <td className="num">{c.peak_uv}</td>
                          <td className="num">{c.snr_db ?? "—"}</td>
                          <td className="num">{c.mains_share_db ?? "—"}</td>
                          <td className="tile-hint">{c.flags.join(", ") || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {(captured.unmapped ?? []).length > 0 && (
                <p className="tile-hint">
                  Без прописи в монтаже, в параметры не вошли:{" "}
                  {(captured.unmapped ?? []).join(", ")}. Допишите канал выше или
                  решите, что он лишний — угадывать мышцу платформа не будет.
                </p>
              )}
              {captured.note && <p className="tile-hint">{captured.note}</p>}
            </Card>
          )}
        </>
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
