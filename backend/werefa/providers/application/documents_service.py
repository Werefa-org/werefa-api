"""KYC document storage (UC-10)."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlmodel import Session, col, select

from werefa.core.config import settings
from werefa.shared.models import ProviderDocument, ProviderDocumentPublic, User

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe_filename(name: str) -> str:
    base = _SAFE_NAME.sub("_", name.strip())[:120]
    return base or "upload"


def store_provider_document(
    session: Session,
    *,
    provider_id: uuid.UUID,
    uploader: User,
    upload: UploadFile,
) -> ProviderDocument:
    raw_name = upload.filename or "document"
    fname = _safe_filename(raw_name)
    doc_id = uuid.uuid4()
    root = Path(settings.KYC_DOCUMENTS_DIR).resolve()
    dest_dir = root / str(provider_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    rel = f"{provider_id}/{doc_id}_{fname}"
    dest = root / rel
    content = upload.file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 15MB)")
    dest.write_bytes(content)
    ct = upload.content_type or "application/octet-stream"
    row = ProviderDocument(
        id=doc_id,
        provider_id=provider_id,
        uploaded_by_user_id=uploader.id,
        filename=raw_name[:255],
        content_type=ct[:120],
        storage_relpath=rel,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_documents(
    session: Session, *, provider_id: uuid.UUID
) -> list[ProviderDocument]:
    rows = session.exec(
        select(ProviderDocument)
        .where(ProviderDocument.provider_id == provider_id)
        .order_by(col(ProviderDocument.created_at).desc())
    ).all()
    return list(rows)


def get_document_path(
    session: Session, *, provider_id: uuid.UUID, doc_id: uuid.UUID
) -> Path:
    row = session.get(ProviderDocument, doc_id)
    if row is None or row.provider_id != provider_id:
        raise HTTPException(status_code=404, detail="Document not found")
    root = Path(settings.KYC_DOCUMENTS_DIR).resolve()
    path = (root / row.storage_relpath).resolve()
    if not str(path).startswith(str(root)):
        raise HTTPException(status_code=404, detail="Invalid storage path")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return path


def document_public(row: ProviderDocument) -> ProviderDocumentPublic:
    return ProviderDocumentPublic(
        id=row.id,
        provider_id=row.provider_id,
        filename=row.filename,
        content_type=row.content_type,
        created_at=row.created_at,
    )
