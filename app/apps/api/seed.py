"""Демо-данные: сессия из ТЗ целиком, чтобы приложение показывало смысл сразу.

Значения синтетические. Пороги — demo, поэтому любые суждения о значимости
в этих данных недействительны; это же печатается баннером на всех экранах.
"""
from __future__ import annotations

import asyncio
import random
import sys
from pathlib import Path

PACKAGES = Path(__file__).resolve().parents[2] / "packages"
if str(PACKAGES) not in sys.path:
    sys.path.insert(0, str(PACKAGES))

from sqlalchemy import select

from .db import engine, sessionmaker
from .models import (
    Analysis, Base, Measurement, PatientRef, Session, SessionPlan, Trial,
)
from .services.bundle import bundle_from_settings
from .services.session_service import load_session, materialize_param_values, run_analysis
from .settings import get_settings

PLAN = [
    ("MAND_NEUTRAL_WITH_APPARATUS", "reference", 0),
    ("MAND_CLENCH", "diagnostic", 400),
    ("CTRL_SHAM_MANDIBULAR", "control", 900),
    ("MAND_LAT_LEFT", "diagnostic", 1400),
    ("MAND_NEUTRAL_WITH_APPARATUS", "reference", 1800),
    ("MAND_LAT_RIGHT", "diagnostic", 2200),
    ("PODAL_WEDGE_L", "podal", 2700),
    ("MAND_SPLINT_THERAPEUTIC", "therapeutic", 3300),
    ("MAND_NEUTRAL_WITH_APPARATUS", "reference", 3900),
]

BASE = {
    "TRUNK_IMBALANCE_VP_DM": 8.2, "SAGITTAL_IMBALANCE_VP_DM": 22.5,
    "LATERAL_DEVIATION_RMS": 6.1, "LATERAL_DEVIATION_MAX": 11.4,
    "VERTEBRAL_ROTATION_RMS": 4.2, "KYPHOTIC_ANGLE_ICT_ITL": 45.3,
    "LORDOTIC_ANGLE_ITL_ILS": 38.9, "PELVIC_OBLIQUITY_DL_DR": 3.4,
    "PELVIC_TORSION": 2.1, "PELVIC_TILT": 10.2, "TRUNK_INCLINATION": 3.6,
    # Таз целиком: ротация и УГЛОВОЙ перекос. Без них схема таза оставалась
    # пустой на каждой пробе — прибор эти величины даёт, а демо их не порождало.
    "PELVIC_ROTATION": 2.8, "PELVIC_OBLIQUITY_ANGLE": 4.1,
}

#: Подометрия. Отдельным словарём, потому что это ДРУГАЯ модальность: доли
#: нагрузки суммируются в 100 %, и портить это шумом по каждому каналу нельзя.
BASE_PEDOSCAN = {"COP_PATH_LENGTH": 210.0, "COP_AREA": 94.0}
BASE_LOAD_LEFT = 47.5

#: Ось ног — СТРУКТУРНАЯ величина (§14.2 п. 8): от пробы к пробе не меняется и
#: сдвигов по пробам не получает. Кладётся один раз на сессию.
BASE_LEG_AXIS = {"LEG_AXIS_VARUS_VALGUS_L": -3.2, "LEG_AXIS_VARUS_VALGUS_R": 2.4}

#: Динамика Dynamic4D: та же поза, снятая на дорожке. Отдельный набор величин,
#: а не пересчёт статики — прибор меряет максимум за цикл шага и размах движения.
BASE_DYNAMIC = {
    "DYN_KYPHOTIC_ANGLE_ICT_ITL_MAX": 46.0, "DYN_KYPHOTIC_ANGLE_ICT_ITL_ROM": 7.5,
    "DYN_LORDOTIC_ANGLE_ITL_ILS_MAX": 40.0, "DYN_LORDOTIC_ANGLE_ITL_ILS_ROM": 5.0,
    "DYN_PELVIC_ROTATION": 4.0, "DYN_PELVIC_ROTATION_ROM": 8.0,
    "DYN_PELVIC_OBLIQUITY": 12.0, "DYN_PELVIC_OBLIQUITY_ROM": 13.0,
    "DYN_PELVIC_OBLIQUITY_ANGLE": 6.0,
    "DYN_SAGITTAL_IMBALANCE_VP_DM": 4.0, "DYN_SAGITTAL_IMBALANCE_VP_DM_ROM": 4.0,
}

#: Изометрическая сила под пробой (Р-41): в этом протоколе myoline ставится на
#: тех же условиях, что формометрия, ЭМГ и кондилография.
BASE_MYO = {
    "MYO_FORCE_TRUNK_EXT": 405.0, "MYO_FORCE_TRUNK_FLEX": 292.0,
    "MYO_FORCE_TRUNK_LAT_L": 188.0, "MYO_FORCE_TRUNK_LAT_R": 196.0,
}
BASE_EMG = {
    "EMG_RMS_MASSETER_L": 35.0, "EMG_RMS_MASSETER_R": 36.5,
    "EMG_RMS_TEMPORALIS_L": 21.0, "EMG_RMS_TEMPORALIS_R": 21.8,
    "EMG_RMS_SCM_L": 10.9, "EMG_RMS_SCM_R": 11.3,
    "EMG_RMS_TRAPEZIUS_L": 19.2, "EMG_RMS_TRAPEZIUS_R": 19.8,
    "EMG_RMS_ERECTOR_SPINAE_L": 40.1, "EMG_RMS_ERECTOR_SPINAE_R": 40.7,
}

#: Эффекты по пробам: множители сдвига в единицах SDC.
EFFECTS = {
    "MAND_CLENCH": {"LATERAL_DEVIATION_RMS": 2.4, "PELVIC_TILT": 1.6, "TRUNK_INCLINATION": 1.2,
                    "PELVIC_ROTATION": 1.4, "PELVIC_OBLIQUITY_ANGLE": 1.1},
    "CTRL_SHAM_MANDIBULAR": {"LATERAL_DEVIATION_RMS": 0.2, "PELVIC_TILT": 0.1},
    "MAND_LAT_LEFT": {"LATERAL_DEVIATION_RMS": -1.4, "PELVIC_OBLIQUITY_DL_DR": -1.1,
                      "PELVIC_OBLIQUITY_ANGLE": -0.9, "PELVIC_ROTATION": -1.2},
    "MAND_LAT_RIGHT": {"LATERAL_DEVIATION_RMS": 1.1, "PELVIC_OBLIQUITY_DL_DR": 0.9,
                       "PELVIC_OBLIQUITY_ANGLE": 0.8, "PELVIC_ROTATION": 1.1},
    "PODAL_WEDGE_L": {"PELVIC_OBLIQUITY_DL_DR": -1.8, "LATERAL_DEVIATION_RMS": -0.9,
                      "PELVIC_OBLIQUITY_ANGLE": -1.5, "PELVIC_ROTATION": -0.8},
    "MAND_SPLINT_THERAPEUTIC": {
        "LATERAL_DEVIATION_RMS": -2.6, "PELVIC_TILT": -1.9,
        "TRUNK_IMBALANCE_VP_DM": -1.5, "VERTEBRAL_ROTATION_RMS": -1.2,
        "PELVIC_OBLIQUITY_ANGLE": -1.7, "PELVIC_ROTATION": -1.0,
    },
}

#: Динамические эффекты заданы ИНАЧЕ статических — намеренно. Именно ради этого
#: контраста режимы и разделены (Р-50): сжатие зубов заметно двигает позу стоя,
#: но при ходьбе почти не проявляется, а латеротрузия влево наоборот — стоя тиха,
#: а на дорожке меняет ротацию таза и размах движения. Свести их в один столбец
#: значило бы стереть ровно ту закономерность, которую ищут.
DYN_EFFECTS = {
    "MAND_CLENCH": {"DYN_PELVIC_ROTATION": 0.4, "DYN_KYPHOTIC_ANGLE_ICT_ITL_MAX": 0.3},
    "MAND_LAT_LEFT": {"DYN_PELVIC_ROTATION": -2.3, "DYN_PELVIC_ROTATION_ROM": -1.8,
                      "DYN_PELVIC_OBLIQUITY": -1.6, "DYN_PELVIC_OBLIQUITY_ANGLE": -1.4},
    "MAND_LAT_RIGHT": {"DYN_PELVIC_ROTATION": 1.9, "DYN_PELVIC_OBLIQUITY": 1.3},
    "MAND_SPLINT_THERAPEUTIC": {
        "DYN_PELVIC_OBLIQUITY": -2.1, "DYN_PELVIC_OBLIQUITY_ANGLE": -1.9,
        "DYN_KYPHOTIC_ANGLE_ICT_ITL_MAX": -1.4, "DYN_SAGITTAL_IMBALANCE_VP_DM": -1.2,
    },
    "PODAL_WEDGE_L": {"DYN_PELVIC_OBLIQUITY": -1.5, "DYN_PELVIC_ROTATION_ROM": -0.9},
    "CTRL_SHAM_MANDIBULAR": {"DYN_PELVIC_ROTATION": 0.2},
}

#: Сила и мышечная активность под пробой, в единицах SDC. Сжатие даёт классический
#: конфликт §9.5: поза хуже, сила выше — ровно тот случай, ради которого сигналы
#: держат раздельно, а не складывают в один индекс.
MYO_EFFECTS = {
    "MAND_CLENCH": {"MYO_FORCE_TRUNK_EXT": 1.9, "MYO_FORCE_TRUNK_LAT_R": 1.4},
    "MAND_LAT_LEFT": {"MYO_FORCE_TRUNK_LAT_L": 1.2, "MYO_FORCE_TRUNK_LAT_R": -0.7},
    "MAND_LAT_RIGHT": {"MYO_FORCE_TRUNK_LAT_R": 1.1, "MYO_FORCE_TRUNK_LAT_L": -0.8},
    "MAND_SPLINT_THERAPEUTIC": {
        "MYO_FORCE_TRUNK_EXT": 1.3, "MYO_FORCE_TRUNK_FLEX": 0.9,
        "MYO_FORCE_TRUNK_LAT_L": 0.8, "MYO_FORCE_TRUNK_LAT_R": 0.7,
    },
    "PODAL_WEDGE_L": {"MYO_FORCE_TRUNK_LAT_L": 0.6},
}
EMG_EFFECTS = {
    "MAND_CLENCH": {"EMG_RMS_MASSETER_R": 2.8, "EMG_RMS_MASSETER_L": 1.9,
                    "EMG_RMS_TEMPORALIS_R": 2.1, "EMG_RMS_SCM_R": 1.2},
    "MAND_LAT_LEFT": {"EMG_RMS_MASSETER_L": 1.1, "EMG_RMS_TEMPORALIS_L": 0.9},
    "MAND_LAT_RIGHT": {"EMG_RMS_MASSETER_R": 1.0},
    "MAND_SPLINT_THERAPEUTIC": {"EMG_RMS_MASSETER_R": -1.4, "EMG_RMS_TRAPEZIUS_R": -1.1,
                                "EMG_RMS_ERECTOR_SPINAE_R": -0.9},
}


#: Смещение опоры по пробам, п.п. на левую стопу. Клин под левую пятку
#: перераспределяет нагрузку — это и есть смысл подометрической пробы.
LOAD_SHIFT = {
    "PODAL_WEDGE_L": 3.4, "MAND_CLENCH": -1.8, "MAND_LAT_LEFT": 1.2,
    "MAND_LAT_RIGHT": -1.1, "MAND_SPLINT_THERAPEUTIC": 1.6,
    "CTRL_SHAM_MANDIBULAR": 0.1,
}


def _pedoscan(code: str, scale: float, rng: random.Random) -> dict[str, float]:
    """Подометрия пробы. Доли нагрузки дополняют друг друга до 100 %.

    Шуметь ими независимо нельзя: сумма перестала бы равняться сотне, а это не
    погрешность прибора, а нарушение определения величины.
    """
    left = BASE_LOAD_LEFT * scale + LOAD_SHIFT.get(code, 0.0) + rng.gauss(0, 0.6)
    left = max(20.0, min(80.0, left))
    out = {"LOAD_SHARE_LEFT": round(left, 2), "LOAD_SHARE_RIGHT": round(100.0 - left, 2)}
    for param, base_value in BASE_PEDOSCAN.items():
        out[param] = round(base_value * scale + rng.gauss(0, base_value * 0.06), 2)
    return out


def _asymmetry(params: dict[str, float], prefix: str, out_prefix: str) -> None:
    """Асимметрия по парам L/R — единая формула для ЭМГ и силы (Р-41)."""
    bases = {c[:-2] for c in params if c.endswith(("_L", "_R")) and c.startswith(prefix)}
    for base in bases:
        r, l = params.get(f"{base}_R"), params.get(f"{base}_L")
        if r is None or l is None or (abs(r) + abs(l)) == 0:
            continue
        name = base[len(prefix):] if prefix.endswith("_") else base
        params[f"{out_prefix}{name}"] = round(200 * (r - l) / (abs(r) + abs(l)), 2)


async def seed(patients: int = 6) -> None:
    s = get_settings()
    bundle = bundle_from_settings(s)
    rng = random.Random(20260816)

    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with sessionmaker()() as db:
        if (await db.execute(select(Session).limit(1))).scalar_one_or_none():
            print("демо-данные уже есть, пропускаю")
            return

        for idx in range(patients):
            ref = f"pref-{rng.getrandbits(64):016x}"
            db.add(PatientRef(patient_ref=ref, neutral_definition="habitual_occlusion"))
            await db.flush()

            session = Session(
                patient_ref=ref, protocol_version=s.protocol_version,
                operator_ref=f"op-{idx % 2 + 1}", study_mode=True,
                randomization_scheme="random_within_group", randomization_seed=1000 + idx,
                patient_blinded=True, operator_blinded=True,
                neutral_definition="habitual_occlusion", lld_mm=round(rng.uniform(0, 8), 1),
                platform_config_baseline={"heel_lift_mm": 0},
                informed_consent_ref=f"ids-{idx}", research_consent_ref=f"res-{idx}",
                status="prepared", **bundle.versions,
            )
            db.add(session)
            await db.flush()

            db.add(SessionPlan(
                session_id=session.id,
                probes=[{"probe_code": c, "position": i, "pass_no": 1}
                        for i, (c, _r, _t) in enumerate(PLAN)],
                randomization={"scheme": "random_within_group", "seed": 1000 + idx},
                approved_by="op-1",
            ))
            session.status = "plan_approved"

            personal = {k: v * rng.uniform(0.85, 1.15) for k, v in BASE.items()}
            personal_scale = rng.uniform(0.88, 1.12)   # общий масштаб ЭМГ и силы пациента
            drift_rate = rng.uniform(-8e-6, 8e-6)   # ~3% за час, физиологичный дрейф позы

            for position, (code, role, t) in enumerate(PLAN):
                spec = bundle.probes.get(code)
                assert spec is not None
                trial = Trial(
                    session_id=session.id, probe_code=code, ordinal=position, pass_no=1,
                    role=role, is_baseline=spec.is_neutral, t_offset_sec=float(t),
                    settle_sec_actual=spec.settle_sec + rng.randint(0, 40),
                    minutes_since_prev_group=float(rng.randint(3, 20)),
                    excursion_mm=round(rng.uniform(6, 11), 1) if spec.requires_excursion else None,
                    effort={"achieved_pct": rng.randint(70, 95)} if spec.requires_effort else {},
                )
                db.add(trial)
                await db.flush()

                values: dict[str, float] = {}
                for param, base_value in personal.items():
                    sdc = bundle.thresholds.sdc(param) or 1.0
                    shift = EFFECTS.get(code, {}).get(param, 0.0) * sdc
                    noise = rng.gauss(0, sdc * 0.18)
                    values[param] = round(base_value + shift + noise + base_value * drift_rate * t, 3)
                db.add(Measurement(
                    trial_id=trial.id, modality="formetric", params=values,
                    quality_flags=[] if rng.random() > 0.12 else ["excess_sway"],
                ))

                # Одноимённые пробы на всех приборах (Р-41): под тем же условием
                # снимаются ЭМГ и изометрическая сила, а не только формометрия.
                for modality, base_values, effects, flags in (
                    ("emg", BASE_EMG, EMG_EFFECTS, ["emg_amplitude_session_scoped"]),
                    ("myoline", BASE_MYO, MYO_EFFECTS, []),
                ):
                    params: dict[str, float] = {}
                    for param, base_value in base_values.items():
                        sdc = bundle.thresholds.sdc(param) or 1.0
                        shift = effects.get(code, {}).get(param, 0.0) * sdc
                        params[param] = round(
                            base_value * personal_scale + shift + rng.gauss(0, sdc * 0.2), 2)
                    _asymmetry(params, "EMG_RMS_", "EMG_ASYM_")
                    _asymmetry(params, "MYO_FORCE_", "MYO_ASYM_")
                    db.add(Measurement(trial_id=trial.id, modality=modality,
                                       params=params, quality_flags=flags))

                dyn: dict[str, float] = {}
                for param, base_value in BASE_DYNAMIC.items():
                    sdc = bundle.thresholds.sdc(param) or 1.0
                    shift = DYN_EFFECTS.get(code, {}).get(param, 0.0) * sdc
                    dyn[param] = round(base_value * personal_scale + shift
                                       + rng.gauss(0, sdc * 0.2), 2)
                # Границы размаха печатаются прибором отдельно; здесь они
                # выводятся из максимума и размаха, как на листе.
                for base in ("DYN_PELVIC_ROTATION", "DYN_PELVIC_OBLIQUITY"):
                    span = dyn.get(f"{base}_ROM")
                    if span is not None:
                        dyn[f"{base}_ROM_MIN"] = round(dyn[base] - span / 2, 2)
                        dyn[f"{base}_ROM_MAX"] = round(dyn[base] + span / 2, 2)
                db.add(Measurement(
                    trial_id=trial.id, modality="formetric_dynamic", params=dyn,
                    quality_flags=["gait_speed_3kmh"],
                ))
                db.add(Measurement(trial_id=trial.id, modality="pedoscan",
                                   params=_pedoscan(code, personal_scale, rng)))
                if position == 0:
                    # Ось ног структурна: измеряется один раз, по пробам не
                    # меняется и Δ не получает (§14.2 п. 8).
                    db.add(Measurement(
                        trial_id=trial.id, modality="leg_axis",
                        params={k: round(v * personal_scale, 2)
                                for k, v in BASE_LEG_AXIS.items()},
                        quality_flags=["structural_no_delta"],
                    ))

            session.status = "probes_running"
            await db.flush()

            # Подтверждающий повтор — ВТОРОЙ ПРОХОД (Р-28), а не отдельная фаза.
            session.status = "imported"
            for j, code in enumerate(("MAND_SPLINT_THERAPEUTIC", "MAND_NEUTRAL_WITH_APPARATUS")):
                spec = bundle.probes.get(code)
                assert spec is not None
                trial = Trial(
                    session_id=session.id, probe_code=code, ordinal=j, pass_no=2, role="therapeutic"
                    if not spec.is_neutral else "reference",
                    is_baseline=spec.is_neutral, t_offset_sec=float(4400 + j * 400),
                    settle_sec_actual=spec.settle_sec + 10, minutes_since_prev_group=16.0,
                )
                db.add(trial)
                await db.flush()
                values = {}
                for param, base_value in personal.items():
                    sdc = bundle.thresholds.sdc(param) or 1.0
                    shift = EFFECTS.get(code, {}).get(param, 0.0) * sdc
                    values[param] = round(base_value + shift + rng.gauss(0, sdc * 0.2), 3)
                db.add(Measurement(trial_id=trial.id, modality="formetric", params=values))
                for modality, base_values, effects, flags in (
                    ("emg", BASE_EMG, EMG_EFFECTS, ["emg_amplitude_session_scoped"]),
                    ("myoline", BASE_MYO, MYO_EFFECTS, []),
                ):
                    params = {}
                    for param, base_value in base_values.items():
                        sdc = bundle.thresholds.sdc(param) or 1.0
                        shift = effects.get(code, {}).get(param, 0.0) * sdc
                        params[param] = round(
                            base_value * personal_scale + shift + rng.gauss(0, sdc * 0.2), 2)
                    _asymmetry(params, "EMG_RMS_", "EMG_ASYM_")
                    _asymmetry(params, "MYO_FORCE_", "MYO_ASYM_")
                    db.add(Measurement(trial_id=trial.id, modality=modality,
                                       params=params, quality_flags=flags))
                db.add(Measurement(trial_id=trial.id, modality="pedoscan",
                                   params=_pedoscan(code, personal_scale, rng)))
            session.pass_count = 2
            session.status = "quality_reviewed"
            await db.flush()

            full = await load_session(db, session.id)
            assert full is not None
            await materialize_param_values(db, full)
            session.status = "shortlist_confirmed"
            result = run_analysis(full, bundle)
            db.add(Analysis(
                session_id=session.id, input_hash=result.input_hash,
                index_kind=result.index_kind, result=result.to_dict(), **result.versions,
            ))
            session.low_confidence = result.low_confidence
            session.status = "analyzed"
            await db.flush()

        await db.commit()
        print(f"создано пациентов: {patients}")


if __name__ == "__main__":
    asyncio.run(seed())
