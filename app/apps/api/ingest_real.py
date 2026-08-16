"""Загрузка реальных приборных данных клиники.

ПДн в модуль не попадают (Р-9, Р-11): пациент представлен непроизводным
непересчислимым `patient_ref`, соответствие ведёт хост. ФИО из заголовка окна
CADIAX и идентификаторы из протокола formetric здесь не хранятся.

Данные:
  • formetric 4D Dynamic4D, 04.03.2025, условие «лев окк», 3 км/ч;
  • CADIAX 4, 30.11.2023, движения «Открывание/закрывание» и «Протрузия/ретрузия».

Даты РАЗНЫЕ — это разные визиты, и §12 запрещает считать между ними разности
без общего набора версий. Загружаются как две отдельные сессии.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "packages", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from sqlalchemy import select

from importers import parse_blob

from .db import engine, sessionmaker
from .models import Base, Measurement, PatientRef, RawImport, Session, SessionPlan, Trial
from .services.bundle import bundle_from_settings
from .services.session_service import load_session, materialize_param_values, run_analysis
from .settings import get_settings

FIXTURES = ROOT / "tests" / "fixtures"
PATIENT = "pref-clinic-real-0001"          # непроизводен от ПДн, соответствие у хоста


async def ingest() -> None:
    s = get_settings()
    bundle = bundle_from_settings(s)

    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with sessionmaker()() as db:
        if await db.get(PatientRef, PATIENT):
            print("реальные данные уже загружены")
            return
        db.add(PatientRef(patient_ref=PATIENT, neutral_definition="habitual_occlusion"))
        await db.flush()

        # ── Визит 1: кондилография CADIAX, 30.11.2023 ────────────────────────
        cdg = Session(
            patient_ref=PATIENT, protocol_version=s.protocol_version,
            started_at=datetime(2023, 11, 30, 14, 16, tzinfo=timezone.utc),
            operator_ref="op-clinic", study_mode=False,
            neutral_definition="habitual_occlusion", lld_mm=0.0,
            platform_config_baseline={"device": "CADIAX 4"},
            informed_consent_ref="ids-clinic-2023", status="prepared", **bundle.versions,
        )
        db.add(cdg)
        await db.flush()
        cdg.status = "plan_approved"
        db.add(SessionPlan(session_id=cdg.id, probes=[], approved_by="op-clinic"))

        for i, (fixture, code) in enumerate((
            ("cadiax_open_close.txt", "CDG_OPEN_CLOSE"),
            ("cadiax_protrusion_retrusion.txt", "CDG_PROTRUSION_RETRUSION"),
        )):
            await _attach(db, cdg, FIXTURES / fixture, code, ordinal=i, t=i * 300.0)
        cdg.status = "imported"
        await db.flush()

        # ── Визит 2: формометрия Dynamic4D, 04.03.2025 ──────────────────────
        fmt = Session(
            patient_ref=PATIENT, protocol_version=s.protocol_version,
            started_at=datetime(2025, 3, 4, 18, 27, tzinfo=timezone.utc),
            operator_ref="op-clinic", study_mode=False,
            neutral_definition="habitual_occlusion", lld_mm=0.0,
            platform_config_baseline={"device": "DIERS formetric 4D", "gait_speed_kmh": 3},
            informed_consent_ref="ids-clinic-2025", status="prepared", **bundle.versions,
        )
        db.add(fmt)
        await db.flush()
        fmt.status = "plan_approved"
        db.add(SessionPlan(session_id=fmt.id, probes=[], approved_by="op-clinic"))
        await _attach(db, fmt, FIXTURES / "formetric_dynamic4d_protocol.txt",
                      "MAND_OCCLUSION_LEFT", ordinal=0, t=0.0)
        fmt.status = "imported"
        await db.flush()

        for session in (cdg, fmt):
            full = await load_session(db, session.id)
            assert full is not None
            await materialize_param_values(db, full)
        await db.commit()
        print(f"загружено: кондилография {cdg.id}, формометрия {fmt.id}")
        print("ВНИМАНИЕ: сессии разных визитов (2023 и 2025) — §12 запрещает "
              "вычислять между ними разности без общего набора версий")


async def _attach(db, session: Session, path: Path, probe_code: str, ordinal: int, t: float) -> None:
    blob = path.read_bytes()
    parser, results = parse_blob(blob)
    bundle = bundle_from_settings(get_settings())
    spec = bundle.probes.get(probe_code)

    trial = Trial(
        session_id=session.id, probe_code=probe_code, ordinal=ordinal, pass_no=1,
        role=spec.role if spec else "diagnostic", mode="dynamic",
        is_baseline=bool(spec and spec.is_neutral), t_offset_sec=t,
        settle_sec_actual=spec.settle_sec if spec else 0,
    )
    db.add(trial)
    await db.flush()

    from domain.hashing import file_hash
    digest = file_hash(blob)
    exists = (await db.execute(select(RawImport).where(RawImport.file_hash == digest))).scalar_one_or_none()
    record = exists or RawImport(
        session_id=session.id, file_hash=digest, modality=parser.modality,
        format_id=parser.format_id, source="manual", status="parsed",
    )
    if exists is None:
        db.add(record)
        await db.flush()

    for res in results:
        db.add(Measurement(
            trial_id=trial.id, raw_import_id=record.id, modality=res.modality,
            params=res.params, unmapped=res.unmapped, quality_flags=res.quality_flags,
        ))
    await db.flush()
    print(f"  {probe_code}: {len(results[0].params)} параметров, "
          f"флаги {results[0].quality_flags or '—'}")


if __name__ == "__main__":
    asyncio.run(ingest())
