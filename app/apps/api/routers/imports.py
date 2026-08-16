from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from contracts.schemas import ImportOut
from domain.hashing import file_hash
from importers import ParserNotFound, parse_blob

from ..db import get_db
from ..models import Measurement, RawImport, Trial
from ..security import Principal, audit, current_principal, require
from ..services.figures import store_figures
from ..services.session_service import load_session, materialize_param_values

router = APIRouter(prefix="/sessions", tags=["imports"])

MAX_BYTES = 32 * 1024 * 1024      # лимит §5, MUST: молчаливого приёма гигабайта нет
ALLOWED_SUFFIX = (".csv", ".txt", ".xml", ".c3d", ".edf", ".pdf")


@router.post("/{session_id}/imports", response_model=ImportOut, status_code=status.HTTP_201_CREATED)
async def upload(
    session_id: UUID,
    trial_id: UUID,
    source: str = "manual",
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require("operator", "clinician", "admin")),
) -> ImportOut:
    session = await load_session(db, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "сессия не найдена")
    trial = await db.get(Trial, trial_id)
    if trial is None or trial.session_id != session.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "проба не найдена в этой сессии")
    if not (file.filename or "").lower().endswith(ALLOWED_SUFFIX):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            f"допустимые расширения: {', '.join(ALLOWED_SUFFIX)}")

    blob = await file.read()
    if len(blob) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"файл больше {MAX_BYTES // 1024 // 1024} МБ")

    digest = file_hash(blob)
    existing = (await db.execute(
        select(RawImport).where(RawImport.file_hash == digest)
    )).scalar_one_or_none()
    if existing is not None:
        # §4 инвариант 1: повторная загрузка НЕ создаёт второе обследование.
        return ImportOut(
            id=existing.id, file_hash=existing.file_hash, modality=existing.modality,
            format_id=existing.format_id, source=existing.source,  # type: ignore[arg-type]
            status=existing.status, reason="файл уже импортирован (идемпотентность)",  # type: ignore[arg-type]
            created_at=existing.created_at, measurements=0,
        )

    record = RawImport(session_id=session.id, file_hash=digest, source=source, status="queued")
    db.add(record)
    await db.flush()

    try:
        parser, results = parse_blob(blob)
    except ParserNotFound as e:
        # MUST §5.1: молчаливый пропуск запрещён. Файл остаётся со статусом
        # unrecognized и причиной, а не исчезает.
        record.status, record.reason = "unrecognized", str(e)
        await db.flush()
        await audit(db, principal, "import.unrecognized", "raw_import", str(record.id),
                    payload={"filename": file.filename})
        return ImportOut(id=record.id, file_hash=digest, modality=None, format_id=None,
                         source=source, status="unrecognized", reason=record.reason,  # type: ignore[arg-type]
                         created_at=record.created_at, measurements=0)
    except Exception as e:                                  # noqa: BLE001
        record.status, record.reason = "failed", f"{type(e).__name__}: {e}"
        await db.flush()
        return ImportOut(id=record.id, file_hash=digest, modality=None, format_id=None,
                         source=source, status="failed", reason=record.reason,  # type: ignore[arg-type]
                         created_at=record.created_at, measurements=0)

    record.modality, record.format_id = parser.modality, parser.format_id
    record.device_sw_version = results[0].device_sw_version if results else None
    record.status = "parsed"

    for res in results:
        db.add(Measurement(
            trial_id=trial.id, raw_import_id=record.id, modality=res.modality,
            params=res.params, unmapped=res.unmapped, quality_flags=res.quality_flags,
        ))
    store_figures(db, record, trial, results)
    await db.flush()

    session = await load_session(db, session_id)
    if session is not None:
        await materialize_param_values(db, session)
        if session.status == "probes_running":
            session.status = "imported"       # неявный переход (Р-7)
    await db.flush()
    await audit(db, principal, "import.parsed", "raw_import", str(record.id),
                payload={"format": parser.format_id, "measurements": len(results)})
    return ImportOut(
        id=record.id, file_hash=digest, modality=record.modality, format_id=record.format_id,
        source=source, status="parsed", reason=None,  # type: ignore[arg-type]
        created_at=record.created_at, measurements=len(results),
    )


@router.get("/{session_id}/imports", response_model=list[ImportOut])
async def queue(
    session_id: UUID, db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> list[ImportOut]:
    rows = (await db.execute(
        select(RawImport).where(RawImport.session_id == session_id).order_by(RawImport.created_at)
    )).scalars().all()
    return [
        ImportOut(id=r.id, file_hash=r.file_hash, modality=r.modality, format_id=r.format_id,
                  source=r.source, status=r.status, reason=r.reason,  # type: ignore[arg-type]
                  created_at=r.created_at)
        for r in rows
    ]
