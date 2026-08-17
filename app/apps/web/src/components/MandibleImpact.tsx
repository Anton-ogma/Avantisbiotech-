/** Какое положение челюсти значимо меняет позу (Р-49).
 *
 *  Главный вопрос протокола, вынесенный в начало отчёта. Раньше ответ на него
 *  надо было собирать глазами из раскладки по вердиктам — при десятке проб это
 *  работа, которую делает читатель, а не платформа.
 *
 *  ЧТО ЗНАЧИТ «ЗНАЧИМО» ЗДЕСЬ. Ровно одно: |Δ| постурального отклика не меньше
 *  порога SDC. Не «клинически важно», не «показано к назначению» — измеренная
 *  величина превысила собственный порог различимости прибора. Порог назван
 *  рядом числом: слово «значимо» без него — риторика.
 *
 *  ЧЕГО ЗДЕСЬ НЕТ. Направления «лучше/хуже» там, где оно не установлено (Р-18):
 *  такая проба попадает в «меняет позу, знак не установлен», а не в улучшения.
 *  Разница существенна — именно в этой графе живут закономерности, которых ещё
 *  никто не назвал, и записать их в «ухудшение» значило бы потерять их.
 */
import type { CrossModal, ProbeSynthesis, Signal } from "../lib/api";
import { Banner, Card, Empty } from "./ui";

/** Пробы положения челюсти. Клин под пятку и sham отвечают на другие вопросы. */
const MANDIBULAR = (p: ProbeSynthesis) =>
  p.group === "mandibular" || (!p.group && p.probe_code.startsWith("MAND_"));

type Bucket = "changes_known" | "changes_unsigned" | "quiet" | "not_measured";

const BUCKET: Record<Bucket, { title: string; tone: string; hint: string }> = {
  changes_known: {
    title: "Значимо меняет позу",
    tone: "good",
    hint: "|Δ| выше порога, направление установлено",
  },
  changes_unsigned: {
    title: "Меняет позу, знак не установлен",
    tone: "neutral",
    hint: "отклик достоверен по величине, но ни один изменившийся параметр не "
        + "имеет подтверждённого направления — назначить знак нечем (Р-18)",
  },
  quiet: {
    title: "В пределах шума",
    tone: "neutral",
    hint: "|Δ| ниже порога различимости: изменения не отличить от повторного измерения",
  },
  not_measured: {
    title: "Поза не измерена",
    tone: "neutral",
    hint: "под этой пробой нет формометрии — это отсутствие данных, а не результат",
  },
};

/** Ячейка режима: значимо / в шуме / не снималось. Три состояния, не два:
 *  «не снималось» — отсутствие данных, и выдавать его за «нет изменений»
 *  значит объявить результатом то, чего не измеряли. */
function ModeCell({ signal }: { signal?: Signal }) {
  if (!signal || !signal.available) {
    return <span className="muted">не снималось</span>;
  }
  if (signal.delta === null) return <span className="muted">Δ не вычислен</span>;
  const big = signal.reliable;
  // Знак показывается ТОЛЬКО когда направление установлено. Иначе «+8.53»
  // рядом с «−11.32» читается как ухудшение, хотя это лишь величина сдвига:
  // у динамических параметров направление по умолчанию не установлено (Р-18).
  const signed = signal.detail.includes("направление установлено");
  const value = signed
    ? `${signal.delta > 0 ? "+" : ""}${signal.delta.toFixed(2)}`
    : `|Δ| ${Math.abs(signal.delta).toFixed(2)}`;
  return (
    <>
      <span className={`badge ${big ? "accent" : ""}`}>{value}</span>
      <div className="tile-hint">
        {big ? "значимо" : "в пределах шума"}
        {!signed && big ? " · знак не установлен" : ""}
      </div>
    </>
  );
}

function bucketOf(p: ProbeSynthesis): Bucket {
  if (!p.posture.available) return "not_measured";
  if (p.posture.delta === null || !p.posture.reliable) return "quiet";
  return p.verdict === "unsigned" ? "changes_unsigned" : "changes_known";
}

/** Куда сдвинулась поза — словами, и только когда знак установлен. */
function direction(p: ProbeSynthesis): string {
  if (p.posture.delta === null) return "";
  if (p.verdict === "unsigned") return "направление не установлено";
  return p.posture.delta < 0 ? "поза улучшается" : "поза ухудшается";
}

export function MandibleImpact({ data }: { data: CrossModal }) {
  const probes = (data.probes ?? []).filter(MANDIBULAR);
  const threshold = data.threshold ?? 2.0;

  if (probes.length === 0) {
    return (
      <>
        <div className="section-title">Положение челюсти и поза</div>
        <Card>
          <Empty text={
            "В сессии нет проб положения нижней челюсти. Вопрос «какое положение "
            + "меняет позу» задаётся к ним; клин под пятку и контрольная проба "
            + "отвечают на другие вопросы."
          } />
        </Card>
      </>
    );
  }

  const groups: Record<Bucket, ProbeSynthesis[]> = {
    changes_known: [], changes_unsigned: [], quiet: [], not_measured: [],
  };
  for (const p of probes) groups[bucketOf(p)].push(p);
  for (const key of Object.keys(groups) as Bucket[]) {
    groups[key].sort((a, b) => Math.abs(b.posture.delta ?? 0) - Math.abs(a.posture.delta ?? 0));
  }
  const moving = groups.changes_known.length + groups.changes_unsigned.length;

  return (
    <>
      <div className="section-title">Положение челюсти и поза</div>

      {data.thresholds_are_demo && (
        <Banner text={
          "Пороги некалиброваны (demo): «значимо» здесь означает превышение "
          + "демонстрационного порога, а не установленной различимости прибора. "
          + "Пороги приходят из режима повторяемости."
        } />
      )}

      <Card>
        <p className="tile-hint" style={{ marginTop: 0 }}>
          {moving === 0
            ? `Ни одно из ${probes.length} положений челюсти не сдвинуло позу выше порога.`
            : `Позу меняют ${moving} положения из ${probes.length}.`}
          {" "}Значимо — это |Δ| ≥ {threshold} в единицах SDC, то есть сдвиг больше
          собственного разброса повторного измерения. Классификация описывает
          измеренный отклик, а не назначение: переход к «назначить» делает врач.
        </p>
        <p className="tile-hint">
          Столбцы «стоя» и «при ходьбе» — тот же отклик, посчитанный по статическим
          и динамическим величинам ОТДЕЛЬНО. Это разные измерения одной позы, и
          положение челюсти может двигать одно, не трогая другое; свёрнутые в
          общий столбец, они это скрывают. «Не снималось» — отсутствие данных,
          а не отсутствие изменений.
        </p>

        {groups.changes_known.concat(groups.changes_unsigned)
          .some((p) => p.role === "control") && (
          <p className="tile-hint">
            Среди сдвинувших позу есть <strong>контрольная</strong> проба. Это
            находка о методе, а не о лечебном положении: аппарат без
            терапевтического позиционирования двигает позу сам по себе, и на
            эту величину нужно поправлять остальные пробы.
          </p>
        )}

        {(Object.keys(BUCKET) as Bucket[]).filter((k) => groups[k].length > 0).map((key) => (
          <div key={key} style={{ marginTop: 14 }}>
            <div className="row">
              <span className={`badge ${BUCKET[key].tone}`}>{BUCKET[key].title}</span>
              <span className="tile-hint" style={{ flex: 1 }}>{BUCKET[key].hint}</span>
            </div>
            <div className="table-wrap" style={{ marginTop: 8 }}>
              <table>
                <thead>
                  <tr>
                    <th>Положение челюсти</th>
                    <th className="num">Δ позы, SDC</th>
                    <th className="num">Стоя</th>
                    <th className="num">При ходьбе</th>
                    <th>Что сдвинулось сильнее всего</th>
                    <th>Согласованность</th>
                  </tr>
                </thead>
                <tbody>
                  {groups[key].map((p) => {
                    const top = [...(p.params ?? [])]
                      .filter((x) => x.effect_size !== null)
                      .sort((a, b) => Math.abs(b.effect_size ?? 0) - Math.abs(a.effect_size ?? 0))
                      .slice(0, 2);
                    return (
                      <tr key={p.probe_code} className={key === "changes_known" ? "row-accent" : undefined}>
                        <td>
                          <strong>{p.label_ru}</strong>
                          {p.role === "control" && (
                            // Sham — челюстная проба, но КОНТРОЛЬНАЯ. Сдвиг под
                            // ней говорит о методе (аппарат сам по себе двигает
                            // позу), а не о лечебном положении, и читаться как
                            // терапевтическая находка не должен.
                            <span className="badge" style={{ marginLeft: 6 }}>контроль</span>
                          )}
                          <div className="mono">{p.probe_code}</div>
                        </td>
                        <td className="num">
                          {p.posture.delta === null ? "—" : (
                            <>
                              {p.posture.delta > 0 ? "+" : ""}{p.posture.delta.toFixed(2)}
                              <div className="tile-hint">{direction(p)}</div>
                            </>
                          )}
                        </td>
                        <td className="num"><ModeCell signal={p.posture_static} /></td>
                        <td className="num"><ModeCell signal={p.posture_dynamic} /></td>
                        <td>
                          {top.length === 0 ? <span className="muted">—</span> : top.map((x) => (
                            <div key={x.code} className="tile-hint">
                              {x.label_ru}: {x.delta > 0 ? "+" : ""}{x.delta}
                              {x.effect_size !== null && ` (${x.effect_size.toFixed(1)} SDC)`}
                            </div>
                          ))}
                        </td>
                        <td className="tile-hint">
                          {p.coherence === "full" ? "сходятся все измеренные сигналы"
                            : p.coherence === "partial" ? "сходится часть сигналов"
                            : p.coherence === "posture_muscle_conflict" ? "конфликт позы и мышцы"
                            : p.coherence === "posture_only" ? "только поза"
                            : "не определена"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </Card>
    </>
  );
}
