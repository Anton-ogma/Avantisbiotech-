import { useEffect, useState } from "react";
import { api, type Passport } from "../lib/api";
import { Banner, Card, Empty, Tile } from "../components/ui";

/** Этап 1.5 — режим повторяемости. Платформа ПОРОЖДАЕТ пороги, а не только
 *  принимает: внешнего источника SDC для этой комбинации оборудования нет. */
export function Repeatability() {
  const [data, setData] = useState<{ passports: Passport[]; operator_variance_share: number | null; warning: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.repeatability().then(setData).catch((e) => setError(e.message)); }, []);

  const opShare = data?.operator_variance_share;
  return (
    <>
      <h1 className="title">Повторяемость</h1>
      <p className="subtitle">
        Test-retest по повторным нейтралям: ICC, SEM, SDC. Это паспорт параметра и
        источник продуктовых порогов — до его выпуска суждения о значимости
        недействительны, потому что мерить их нечем.
      </p>

      {error && <Banner text={error} />}
      {data?.warning && <Banner text={data.warning} />}
      {opShare !== null && opShare !== undefined && opShare > 0.25 && (
        <Banner text={`Доля дисперсии, приходящаяся на оператора: ${(opShare * 100).toFixed(0)}%. Это сопоставимо с эффектом пробы — выводы недостоверны независимо от статистики. Требуется стандартизация установки пациента.`} />
      )}

      <div className="grid cols-3">
        <Tile label="Параметров с паспортом" value={data?.passports.length ?? "…"} />
        <Tile label="Дисперсия оператора"
              value={opShare === null || opShare === undefined ? "—" : `${(opShare * 100).toFixed(1)}%`}
              tone={opShare && opShare > 0.25 ? "bad" : undefined}
              hint="часто крупнейший источник разброса" />
        <Tile label="Надёжных (ICC ≥ 0.75)"
              value={data ? data.passports.filter((p) => (p.icc ?? 0) >= 0.75).length : "…"} />
      </div>

      <div className="section-title">Паспорта параметров</div>
      <Card>
        {!data?.passports.length ? <Empty text="Данных недостаточно: нужно ≥2 пациентов с ≥2 повторными нейтралями" /> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Параметр</th><th className="num">n</th><th className="num">ICC</th>
                  <th className="num">95% ДИ</th><th className="num">SEM</th><th className="num">SDC</th>
                  <th className="num">CV %</th><th>Надёжность</th>
                  <th className="num">Детектируем при n=30</th>
                </tr>
              </thead>
              <tbody>
                {data.passports.map((p) => (
                  <tr key={p.code}>
                    <td>{p.label_ru}<div className="mono">{p.code}</div></td>
                    <td className="num">{p.n_subjects}</td>
                    <td className="num">{p.icc?.toFixed(3) ?? "—"}</td>
                    <td className="num">{p.icc_ci ? `${p.icc_ci[0].toFixed(2)}…${p.icc_ci[1].toFixed(2)}` : "—"}</td>
                    <td className="num">{p.sem?.toFixed(3) ?? "—"}</td>
                    <td className="num">{p.sdc?.toFixed(3) ?? "—"}</td>
                    <td className="num">{p.cv_pct?.toFixed(1) ?? "—"}</td>
                    <td>
                      <span className={`badge ${(p.icc ?? 0) >= 0.75 ? "good" : (p.icc ?? 0) >= 0.5 ? "neutral" : "bad"}`}>
                        {p.reliability}
                      </span>
                    </td>
                    <td className="num">{p.detectable_at_n30?.toFixed(3) ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
