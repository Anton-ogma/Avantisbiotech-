"""Автоподгрузка: распознавание формата, пробы и модальности без указаний оператора.

Пользователь кидает пачку файлов — формометрию, ЭМГ, кондилографию, myoline —
и не указывает ни модальность, ни к какой пробе относится файл. Система:
  1. определяет формат через detect() каждого парсера;
  2. читает метку условия из самого файла («лев окк», «Открывание/закрывание»);
  3. разрешает метку в код пробы через алиасы реестра — не догадкой парсера;
  4. подшивает измерение к существующей пробе или заводит новую;
  5. сортирует пробы по порядку из реестра: reference → diagnostic → podal →
     therapeutic, внутри группы — по времени поступления.

Нераспознанное не пропадает: файл остаётся со статусом unrecognized и причиной
(MUST §5.1), а неизвестная метка условия — с needs_probe_assignment.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.hashing import file_hash
from domain.montage import MontageError, SessionMontage, apply_montage, build_montage
from importers import ParserNotFound, parse_blob
from importers.emg_csv import EmgCsvParser

from ..db import get_db
from ..models import Measurement, RawImport, Session, Trial
from ..security import Principal, audit, require
from ..services.bundle import bundle_from_session
from ..services.figures import store_figures
from .imports import _readable
from ..services.session_service import load_session, materialize_param_values

router = APIRouter(prefix="/sessions", tags=["ingest"])

MAX_BYTES = 32 * 1024 * 1024
GROUP_ORDER = {"reference": 0, "diagnostic": 1, "control": 1, "podal": 2, "therapeutic": 3}


@dataclass(slots=True)
class FileOutcome:
    filename: str
    status: str
    modality: str | None = None
    format_id: str | None = None
    condition_label: str | None = None
    probe_code: str | None = None
    params: int = 0
    reason: str | None = None



async def _session_montage(db: AsyncSession, session_id) -> "SessionMontage | None":
    """Действующий монтаж сессии, если оператор его задал."""
    from ..models import SessionMontageRow

    row = (await db.execute(
        select(SessionMontageRow)
        .where(SessionMontageRow.session_id == session_id)
        .order_by(SessionMontageRow.created_at.desc(), SessionMontageRow.id.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return None
    try:
        return build_montage(list(row.channels or []), template=row.template, note=row.note)
    except MontageError:
        # Монтаж мог стать недействительным после смены каталога мышц. Разбор
        # от этого не должен падать: файл разберётся тем, что распознаётся само.
        return None


def _emg_by_montage(blob: bytes, montage: "SessionMontage | None"):
    """Повторная попытка открыть файл как ЭМГ, опираясь на монтаж сессии."""
    if montage is None:
        return None
    parser = EmgCsvParser()
    channel_map = montage.channel_map()
    if not parser.detect(blob, channel_map):
        return None
    return parser, parser.parse(blob, channel_map)


@router.post("/{session_id}/auto-ingest")
async def auto_ingest(
    session_id: UUID,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("operator", "clinician", "admin")),
) -> dict:
    session = await load_session(db, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")
    if session.status == "prepared":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "план не утверждён: до утверждения плана пробы не выполняются (Р-29)",
        )
    bundle = bundle_from_session(session)
    montage = await _session_montage(db, session.id)
    outcomes: list[FileOutcome] = []
    touched = False

    for upload in files:
        name = upload.filename or "без имени"
        blob = await upload.read()
        if len(blob) > MAX_BYTES:
            outcomes.append(FileOutcome(name, "rejected", reason="файл больше 32 МБ"))
            continue

        digest = file_hash(blob)
        existing = (await db.execute(
            select(RawImport).where(RawImport.file_hash == digest)
        )).scalar_one_or_none()
        if existing is not None:
            # §4 инвариант 1: повторная загрузка не создаёт второе обследование
            outcomes.append(FileOutcome(name, "duplicate", existing.modality, existing.format_id,
                                        reason="файл уже импортирован"))
            continue

        record = RawImport(session_id=session.id, file_hash=digest, source="manual", status="queued")
        db.add(record)
        await db.flush()

        try:
            parser, results = parse_blob(blob)
        except ParserNotFound as e:
            # Второй заход по монтажу сессии (Р-42): миограф подписывает каналы
            # «CH1…CH8», и по имени столбца мышцу не восстановить ничем. Монтаж —
            # пропись оператора, а не догадка платформы. На ПЕРВОМ заходе он не
            # применяется намеренно: метки вроде «CH1» перетягивали бы на себя
            # посторонние таблицы, где два таких столбца найдутся легко.
            retry = _emg_by_montage(blob, montage)
            if retry is None:
                record.status, record.reason = "unrecognized", str(e)
                outcomes.append(FileOutcome(name, "unrecognized", reason=str(e)))
                continue
            parser, results = retry
        except Exception as e:                                        # noqa: BLE001
            record.status, record.reason = "failed", _readable(e)
            outcomes.append(FileOutcome(name, "failed", reason=record.reason))
            continue

        record.modality, record.format_id, record.status = parser.modality, parser.format_id, "parsed"

        for result in results:
            apply_montage(result, montage)
            label = (result.raw_row.get("condition_label")
                     or result.raw_row.get("movement")
                     or "").strip()
            explicit = result.raw_row.get("movement_code") or ""
            spec = (bundle.probes.get(explicit) if explicit else None) or (
                bundle.probes.by_alias(label) if label else None
            )
            if result.modality == "myoline" and spec is None:
                # Р-41: сила измеряется под пробой и в анализе участвует. Сюда
                # попадают только выгрузки БЕЗ метки условия — архивные файлы,
                # которые к пробе не привязать. Отвергать их нельзя, подставлять
                # под произвольную пробу — тем более.
                trial = await _trial_for(db, session, "MYOLINE_SESSION", bundle)
                db.add(Measurement(
                    trial_id=trial.id, raw_import_id=record.id, modality=result.modality,
                    params=result.params, unmapped=result.unmapped,
                    quality_flags=result.quality_flags,
                ))
                store_figures(db, record, trial, [result])
                touched = True
                outcomes.append(FileOutcome(
                    name, "ingested", parser.modality, parser.format_id,
                    "сессионное измерение", "MYOLINE_SESSION", len(result.params),
                    "в файле нет метки условия: сила осталась сессионной ковариатой "
                    "и в сравнение проб не войдёт",
                ))
                continue

            if spec is None:
                # Метка есть, а кода нет — угадывать нельзя (Р-36). Файл разобран,
                # измерение ждёт назначения пробы человеком.
                record.status = "parsed"
                record.reason = (
                    f"метка условия «{label}» не найдена в реестре проб; "
                    "требуется назначение пробы" if label else
                    "в файле нет метки условия; требуется назначение пробы"
                )
                outcomes.append(FileOutcome(
                    name, "needs_probe_assignment", parser.modality, parser.format_id,
                    label or None, None, len(result.params), record.reason,
                ))
                continue

            trial = await _trial_for(db, session, spec.code, bundle)
            db.add(Measurement(
                trial_id=trial.id, raw_import_id=record.id, modality=result.modality,
                params=result.params, unmapped=result.unmapped, quality_flags=result.quality_flags,
            ))
            store_figures(db, record, trial, [result])
            touched = True
            outcomes.append(FileOutcome(
                name, "ingested", parser.modality, parser.format_id,
                label or None, spec.code, len(result.params),
            ))
        await db.flush()

    if touched:
        await _resort(db, session, bundle)
        full = await load_session(db, session_id)
        if full is not None:
            await materialize_param_values(db, full)
            if full.status in ("plan_approved", "baseline_recorded", "probes_running"):
                full.status = "imported"
    await db.flush()
    await audit(db, principal, "session.auto_ingest", "session", str(session.id),
                payload={"files": len(files),
                         "ingested": sum(1 for o in outcomes if o.status == "ingested")})

    return {
        "session_id": str(session.id),
        "files": [asdict(o) for o in outcomes],
        "summary": {
            "ingested": sum(1 for o in outcomes if o.status == "ingested"),
            "needs_assignment": sum(1 for o in outcomes if o.status == "needs_probe_assignment"),
            "unrecognized": sum(1 for o in outcomes if o.status in ("unrecognized", "failed")),
            "duplicates": sum(1 for o in outcomes if o.status == "duplicate"),
        },
    }


async def _trial_for(db: AsyncSession, session: Session, probe_code: str, bundle) -> Trial:
    """Подшить к существующей пробе или завести новую.

    Измерения РАЗНЫХ модальностей одного условия ложатся на ОДНУ пробу — именно
    это делает стыковку возможной (§6.2, уровень M: сопоставление по коду пробы).
    """
    existing = (await db.execute(
        select(Trial).where(Trial.session_id == session.id, Trial.probe_code == probe_code)
        .order_by(Trial.pass_no)
    )).scalars().first()
    if existing is not None:
        return existing

    spec = bundle.probes.get(probe_code)
    count = (await db.execute(
        select(Trial).where(Trial.session_id == session.id)
    )).scalars().all()
    trial = Trial(
        session_id=session.id, probe_code=probe_code, ordinal=len(count), pass_no=1,
        role=spec.role if spec else "diagnostic",
        mode="dynamic" if spec and "dynamic" in spec.modes else "static",
        is_baseline=bool(spec and spec.is_neutral),
        t_offset_sec=float(len(count) * 300),
        settle_sec_actual=spec.settle_sec if spec else 0,
    )
    db.add(trial)
    await db.flush()
    return trial


async def _resort(db: AsyncSession, session: Session, bundle) -> None:
    """Автосортировка: reference → diagnostic → podal → therapeutic (§8.1.2),
    внутри группы — по порядку поступления."""
    trials = (await db.execute(
        select(Trial).where(Trial.session_id == session.id).order_by(Trial.ordinal)
    )).scalars().all()

    def key(t: Trial) -> tuple[int, int, str]:
        spec = bundle.probes.get(t.probe_code)
        role = spec.role if spec else "diagnostic"
        group = 2 if spec and spec.group == "podal" else GROUP_ORDER.get(role, 1)
        return (t.pass_no, 0 if (spec and spec.is_neutral) else group, t.probe_code)

    for i, trial in enumerate(sorted(trials, key=key)):
        trial.ordinal = i
        trial.t_offset_sec = float(i * 300)
    await db.flush()
