"""Provider KYC documents — stored in Cloudinary."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, UploadFile
from sqlmodel import Session, col, select

from werefa.core import cloudinary_storage
from werefa.core.config import settings
from werefa.providers.domain.verification_documents import (
    KIND_LABELS,
    REQUIRED_VERIFICATION_KINDS,
    infer_kind_from_filename,
    normalize_document_kind,
)
from werefa.shared.enums import VerificationStatus
from werefa.shared.models import (
    Provider,
    ProviderDocument,
    ProviderDocumentPublic,
    ProviderVerificationRequirements,
    User,
)

_MAX_FILENAME_LEN = 120
_MAX_BYTES = 10 * 1024 * 1024
_ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}


def _safe_filename(name: str) -> str:
    base = "".join(c if c.isalnum() or c in "._-" else "_" for c in name.strip())
    return (base[:_MAX_FILENAME_LEN] or "document")


def _validate_upload(upload: UploadFile, content: bytes) -> None:
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > _MAX_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")
    raw_name = upload.filename or "document"
    extension = raw_name[raw_name.rfind(".") :].lower() if "." in raw_name else ""
    mime = (upload.content_type or "").lower()
    allowed_mimes = {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/jpeg",
        "image/png",
    }
    if extension not in _ALLOWED_EXTENSIONS and mime not in allowed_mimes:
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Allowed: PDF, DOC, DOCX, JPG, PNG.",
        )


def store_provider_document(
    session: Session,
    *,
    provider_id: uuid.UUID,
    uploader: User,
    upload: UploadFile,
    document_kind: str,
) -> ProviderDocument:
    try:
        kind = normalize_document_kind(document_kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    content = upload.file.read()
    _validate_upload(upload, content)
    raw_name = upload.filename or "document"
    label = KIND_LABELS.get(kind, kind)
    stored_name = f"{label} — {raw_name}"

    stored = cloudinary_storage.upload_bytes(
        data=content,
        filename=_safe_filename(raw_name),
        folder=f"{settings.CLOUDINARY_FOLDER}/{provider_id}",
    )
    row = ProviderDocument(
        id=uuid.uuid4(),
        provider_id=provider_id,
        uploaded_by_user_id=uploader.id,
        document_kind=kind,
        filename=stored_name[:255],
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


def uploaded_kind_set(session: Session, *, provider_id: uuid.UUID) -> set[str]:
    rows = list_documents(session, provider_id=provider_id)
    kinds: set[str] = set()
    for row in rows:
        kind = (row.document_kind or "").strip()
        if kind and kind != "other":
            kinds.add(kind)
            continue
        inferred = infer_kind_from_filename(row.filename)
        if inferred and inferred != "other":
            kinds.add(inferred)
        elif kind:
            kinds.add(kind)
    return kinds


def verification_requirements(
    session: Session, *, provider_id: uuid.UUID
) -> ProviderVerificationRequirements:
    provider = session.get(Provider, provider_id)
    uploaded = sorted(uploaded_kind_set(session, provider_id=provider_id))
    required = list(REQUIRED_VERIFICATION_KINDS)
    missing = [k for k in required if k not in uploaded]
    is_verified = (
        provider is not None
        and provider.verification_status == VerificationStatus.verified.value
    )
    return ProviderVerificationRequirements(
        required_kinds=required,
        uploaded_kinds=uploaded,
        missing_kinds=missing,
        ready_for_review=is_verified or len(missing) == 0,
        is_verified=is_verified,
    )


def assert_ready_for_verification(session: Session, *, provider_id: uuid.UUID) -> None:
    req = verification_requirements(session, provider_id=provider_id)
    if not req.ready_for_review:
        labels = [KIND_LABELS.get(k, k) for k in req.missing_kinds]
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot approve: missing required documents — "
                + ", ".join(labels)
            ),
        )


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
        document_kind=row.document_kind,
        filename=row.filename,
        content_type=row.content_type,
        created_at=row.created_at,
        url=cloudinary_storage.delivery_url(
            public_id=row.storage_relpath,
            resource_type=row.resource_type,
        ),
    )
