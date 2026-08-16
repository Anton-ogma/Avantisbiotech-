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
}

#: Эффекты по пробам: множители сдвига в единицах SDC.
EFFECTS = {
    "MAND_CLENCH": {"LATERAL_DEVIATION_RMS": 2.4, "PELVIC_TILT": 1.6, "TRUNK_INCLINATION": 1.2},
    "CTRL_SHAM_MANDIBULAR": {"LATERAL_DEVIATION_RMS": 0.2, "PELVIC_TILT": 0.1},
    "MAND_LAT_LEFT": {"LATERAL_DEVIATION_RMS": -1.4, "PELVIC_OBLIQUITY_DL_DR": -1.1},
    "MAND_LAT_RIGHT": {"LATERAL_DEVIATION_RMS": 1.1, "PELVIC_OBLIQUITY_DL_DR": 0.9},
    "PODAL_WEDGE_L": {"PELVIC_OBLIQUITY_DL_DR": -1.8, "LATERAL_DEVIATION_RMS": -0.9},
    "MAND_SPLINT_THERAPEUTIC": {
        "LATERAL_DEVIATION_RMS": -2.6, "PELVIC_TILT": -1.9,
        "TRUNK_IMBALANCE_VP_DM": -1.5, "VERTEBRAL_ROTATION_RMS": -1.2,
    },
}


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
