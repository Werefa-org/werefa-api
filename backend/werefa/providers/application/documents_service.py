"""Provider KYC documents — stored in Cloudinary."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, UploadFile
from sqlmodel import Session, col, select

from werefa.core import cloudinary_storage
from werefa.core.config import settings
from werefa.shared.models import ProviderDocument, ProviderDocumentPublic, User

_MAX_FILENAME_LEN = 120


def _safe_filename(name: str) -> str:
    base = "".join(c if c.isalnum() or c in "._-" else "_" for c in name.strip())
    return (base[:_MAX_FILENAME_LEN] or "document")


def store_provider_document(
    session: Session,
    *,
    provider_id: uuid.UUID,
    uploader: User,
    upload: UploadFile,
) -> ProviderDocument:
    raw_name = upload.filename or "document"
    content = upload.file.read()
    stored = cloudinary_storage.upload_bytes(
        data=content,
        filename=_safe_filename(raw_name),
        folder=f"{settings.CLOUDINARY_FOLDER}/{provider_id}",
    )
    row = ProviderDocument(
        id=uuid.uuid4(),
        provider_id=provider_id,
        uploaded_by_user_id=uploader.id,
        filename=raw_name[:255],
        content_type=(upload.content_type or "application/octet-stream")[:120],
        storage_relpath=stored.public_id,
        resource_type=stored.resource_type[:16],
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


def get_delivery_url(
    session: Session, *, provider_id: uuid.UUID, doc_id: uuid.UUID
) -> str:
    row = session.get(ProviderDocument, doc_id)
    if row is None or row.provider_id != provider_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return cloudinary_storage.delivery_url(
        public_id=row.storage_relpath,
        resource_type=row.resource_type,
    )


def document_public(row: ProviderDocument) -> ProviderDocumentPublic:
    return ProviderDocumentPublic(
        id=row.id,
        provider_id=row.provider_id,
        filename=row.filename,
        content_type=row.content_type,
        created_at=row.created_at,
        url=cloudinary_storage.delivery_url(
            public_id=row.storage_relpath,
            resource_type=row.resource_type,
        ),
    )
