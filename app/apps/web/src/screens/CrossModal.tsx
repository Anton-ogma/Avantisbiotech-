import { useEffect, useState } from "react";
import { api, type CrossModal as CM, type Measurements, type SessionOut } from "../lib/api";
import { CondylarProfile, EmgMirror, SignalTriad, type Channel, type CondylarMetric } from "../components/Modality";
import { DeltaChart } from "../components/DeltaChart";
import { Banner, Card, Empty, Segmented, Tile } from "../components/ui";

const VERDICT_TONE: Record<string, string> = {
  best: "good", worse: "bad", conflicting: "bad",
  unsigned: "neutral", neutral: "neutral", no_posture: "neutral",
};
const BUCKET_TITLE: Record<string, string> = {
  best: "Лучшие по отклику",
  worse: "Ухудшают",
  conflicting: "Конфликт позы и мышцы",
  unsigned: "Отвечают, знак не установлен",
  neutral: "В пределах шума",
  no_posture: "Поза не измерена",
};
const MUSCLE_RU: Record<string, string> = {
  MASSETER: "жеват.", TEMPORALIS: "височ.", SCM: "ГКС", TRAPEZIUS: "трапец.",
  ERECTOR_SPINAE: "выпрям.", QUADRATUS_LUMBORUM: "кв.пояс.", GLUTEUS_MAXIMUS: "ягод.",
  RECTUS_FEMORIS: "пр.бедра", TIBIALIS_ANTERIOR: "перед.б/б", GASTROCNEMIUS: "икр.",
};

export function CrossModalScreen({ sessions }: { sessions: SessionOut[] }) {
  const [selected, setSelected] = useState("");
  const [data, setData] = useState<CM | null>(null);
  const [raw, setRaw] = useState<Measurements | null>(null);
  const [probe, setProbe] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { if (!selected && sessions.length) setSelected(sessions[0].id); }, [sessions, selected]);
  useEffect(() => {
    if (!selected) return;
    setData(null); setError(null);
    Promise.all([api.crossmodal(selected), api.measurements(selected)])
      .then(([c, m]) => { setData(c); setRaw(m); setProbe(c.probes[0]?.probe_code ?? ""); })
      .catch((e) => setError(e.message));
  }, [selected]);

  const current = data?.probes.find((p) => p.probe_code === probe);
  const trial = raw?.trials.find((t) => t.probe_code === probe);

  const emg: Channel[] = [];
  const condylar: CondylarMetric[] = [];
  if (trial) {
    const byMuscle = new Map<string, Channel>();
    const byBase = new Map<string, CondylarMetric>();
    for (const p of trial.params) {
      const emgM = p.code.match(/^EMG_RMS_(.+)_(L|R)$/);
      if (emgM) {
        const row = byMuscle.get(emgM[1]) ?? {
          muscle: emgM[1], label: MUSCLE_RU[emgM[1]] ?? emgM[1].slice(0, 8),
        };
        if (emgM[2] === "L") row.left = p.value; else row.right = p.value;
        byMuscle.set(emgM[1], row);
      }
      const cdgM = p.code.match(/^(CDG_.+)_(L|R)$/);
      if (cdgM) {
        const row = byBase.get(cdgM[1]) ?? {
          base: cdgM[1], label: p.label_ru.replace(/,\s*(справа|слева)$/, ""), unit: p.unit,
        };
        if (cdgM[2] === "L") row.l = p.value; else row.r = p.value;
        byBase.set(cdgM[1], row);
      }
    }
    emg.push(...byMuscle.values());
    condylar.push(...byBase.values());
  }

  return (
    <>
      <h1 className="title">Сравнение проб</h1>
      <p className="subtitle">
        Поза, сустав и мышца сводятся не в один индекс, а в согласованность между собой.
        Классификация описывает измеренный отклик, а не назначение: переход от «даёт
        наибольшее улучшение позы» к «назначить» делает врач.
      </p>
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
        </div>
      </Card>

      {data?.warning && <Banner text={data.warning} />}
      {!data ? <Empty text="Считаю стыковку…" /> : data.probes.length === 0 ? (
        <Card>
          <Empty text={
            data.warning
              ? "Отклики не считаются: в сессии нет нейтрали. Опора нужна, чтобы было от чего отсчитывать Δ."
              : "В сессии нет проб, кроме нейтрали."
          } />
          {Object.keys(data.modalities).length > 0 && (
            <div className="row" style={{ justifyContent: "center", marginTop: 4 }}>
              {Object.entries(data.modalities).map(([code, mods]) => (
                <span key={code} className="badge">{code} · {mods.join(", ")}</span>
              ))}
            </div>
          )}
        </Card>
      ) : (
        <>
          <div className="section-title">Раскладка проб</div>
          <div className="grid cols-3">
            {["best", "worse", "conflicting", "unsigned", "neutral", "no_posture"]
              .filter((b) => (data.ranking[b] ?? []).length)
              .map((b) => (
                <Tile key={b} label={BUCKET_TITLE[b]} value={data.ranking[b].length}
                      tone={VERDICT_TONE[b] as any}
                      hint={data.ranking[b].map((c) => c.replace(/^(MAND|PODAL|CTRL|CDG)_/, "")).join(", ")} />
              ))}
          </div>

          <div className="section-title">Проба</div>
          <Card>
            <Segmented value={probe}
                       options={data.probes.map((p) => ({
                         value: p.probe_code,
                         label: p.probe_code.replace(/^(MAND|PODAL|CTRL|CDG)_/, ""),
                       }))}
                       onChange={setProbe} />
            {current && (
              <>
                <div className="row" style={{ marginTop: 14 }}>
                  <span className={`badge ${VERDICT_TONE[current.verdict]}`}>{current.verdict_ru}</span>
                  <span className="badge">когерентность: {current.coherence}</span>
                  {(data.modalities[current.probe_code] ?? []).map((m) => (
                    <span key={m} className="badge accent">{m}</span>
                  ))}
                </div>
                <p className="tile-hint" style={{ marginTop: 10 }}>{current.rationale}</p>
                {current.excursion && current.excursion.status !== "absent" && (
                  <div style={{ marginTop: 10 }}>
                    <span className={`badge ${current.excursion.status === "matched" ? "good" : "bad"}`}>
                      сверка экскурсии: {current.excursion.status}
                    </span>
                    <div className="tile-hint">{current.excursion.message}</div>
                  </div>
                )}
              </>
            )}
          </Card>

          {current && (
            <>
              <div className="section-title">Три сигнала пробы</div>
              <Card>
                <SignalTriad posture={current.posture.delta} joint={current.joint.delta}
                             muscle={current.muscle.delta} threshold={2.0} />
                <div className="grid cols-3" style={{ marginTop: 12 }}>
                  {(["posture", "joint", "muscle"] as const).map((k) => (
                    <div key={k} className="tile-hint">
                      <strong>{k === "posture" ? "Поза" : k === "joint" ? "Сустав" : "Мышца"}:</strong>{" "}
                      {current[k].detail}
                    </div>
                  ))}
                </div>
              </Card>

              {current.posture.available && current.params.length > 0 && (
                <>
                  <div className="section-title">Формометрия · параметры</div>
                  <Card><DeltaChart params={current.params as any} /></Card>
                </>
              )}

              {emg.length > 0 && (
                <>
                  <div className="section-title">ЭМГ · каналы по сторонам</div>
                  <Card>
                    <EmgMirror channels={emg} />
                    <p className="tile-hint">
                      Амплитуды в мкВ сравнимы только внутри одной сессии: между сессиями
                      электроды переклеиваются, и межсессионная динамика без нормализации
                      не строится.
                    </p>
                  </Card>
                </>
              )}

              {condylar.length > 0 && (
                <>
                  <div className="section-title">Кондилография · профиль суставного угла</div>
                  <Card>
                    <CondylarProfile metrics={condylar} />
                    <p className="tile-hint">
                      Расхождение кривых сторон и есть суставной сигнал. В постуральный
                      индекс он не суммируется — это отдельная из трёх составляющих.
                    </p>
                  </Card>
                </>
              )}
            </>
          )}

          {data.session_level?.myoline && Object.keys(data.session_level.myoline).length > 0 && (
            <>
              <div className="section-title">Изометрическая сила · сессионное измерение</div>
              <Card>
                <div className="grid cols-4">
                  {Object.entries(data.session_level.myoline).map(([k, v]) => (
                    <Tile key={k} label={k.replace("MYO_FORCE_", "")} value={`${v} Н`} />
                  ))}
                </div>
                <p className="tile-hint">{data.session_level.note}</p>
              </Card>
            </>
          )}
        </>
      )}
    </>
  );
}
