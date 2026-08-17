from __future__ import annotations

from pathlib import Path
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


def _readable(exc: Exception) -> str:
    """Причина отказа словами оператора, а не именем класса исключения.

    «PdfStreamError: Stream has ended unexpectedly» ничего не говорит человеку,
    который только что перетащил недокачанный отчёт. Класс исключения при этом
    сохраняется в хвосте: разбирать инцидент по журналу всё равно придётся.
    """
    known = {
        "PdfStreamError": "файл повреждён или скачан не полностью",
        "PdfReadError": "PDF не читается: возможно, он зашифрован или повреждён",
        "UnicodeDecodeError": "кодировка файла не распознана",
        "EmptyFileError": "файл пуст",
    }
    hint = known.get(type(exc).__name__)
    return f"{hint} ({type(exc).__name__})" if hint else f"{type(exc).__name__}: {exc}"

router = APIRouter(prefix="/sessions", tags=["imports"])

MAX_BYTES = 32 * 1024 * 1024      # лимит §5, MUST: молчаливого приёма гигабайта нет
#: Снимки экрана приняты сюда осознанно (Р-44): проводной миограф часто не
#: даёт выгрузки вообще, и до этого такой файл терялся целиком.
ALLOWED_SUFFIX = (".csv", ".txt", ".xml", ".c3d", ".edf", ".pdf",
                  ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


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
        # Имя файла в журнал не пишется: клиника называет выгрузки по пациенту
        # («Петрова Жанна.pdf»), и ПДн попали бы в постоянное хранилище модуля
        # вопреки Р-9 и ФЗ-152. Для разбора инцидента достаточно расширения и
        # размера — сам файл лежит по хешу.
        await audit(db, principal, "import.unrecognized", "raw_import", str(record.id),
                    payload={"suffix": Path(file.filename or "").suffix.lower(),
                             "bytes": len(blob)})
        return ImportOut(id=record.id, file_hash=digest, modality=None, format_id=None,
                         source=source, status="unrecognized", reason=record.reason,  # type: ignore[arg-type]
                         created_at=record.created_at, measurements=0)
    except Exception as e:                                  # noqa: BLE001
        record.status, record.reason = "failed", _readable(e)
        await db.flush()
        return ImportOut(id=record.id, file_hash=digest, modality=None, format_id=None,
                         source=source, status="failed", reason=record.reason,  # type: ignore[arg-type]
                         created_at=record.created_at, measurements=0)

    if len(results) > 1:
        # Многораздельный отчёт: одно условие на раздел. Ручная загрузка
        # привязывает файл к ОДНОЙ пробе, и сложить сюда все разделы значило бы
        # смешать условия в одной пробе — молча и правдоподобно. Такой файл
        # разбирает автоподгрузка: она раскладывает разделы по пробам сама.
        record.status, record.reason = "rejected", (
            f"в файле {len(results)} разделов с разными условиями "
            f"({', '.join(sorted({r.raw_row.get('condition_label', '?') for r in results}))}); "
            "ручная привязка к одной пробе смешала бы их — загрузите через автоподгрузку"
        )
        await db.flush()
        raise HTTPException(status.HTTP_409_CONFLICT, record.reason)

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
