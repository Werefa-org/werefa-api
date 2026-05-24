"""Join-time document requirements and ticket uploads."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlmodel import Session, select

from werefa.core import cloudinary_storage
from werefa.core.config import settings
from werefa.providers.application import documents_service as kyc_docs
from werefa.shared.enums import JoinDocumentKind
from werefa.shared.models import (
    JoinDocumentRequirement,
    ServiceItem,
    TicketJoinDocument,
    TicketJoinDocumentPublic,
)

_MAX_SLOTS = 8

_IMAGE_MIMES = frozenset(
    {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
        "image/gif",
        "image/heic",
        "image/heif",
    }
)
_PDF_MIMES = frozenset({"application/pdf"})


def kind_label(kind: str) -> str:
    if kind == JoinDocumentKind.image.value:
        return "Photo or picture (JPG, PNG)"
    if kind == JoinDocumentKind.pdf.value:
        return "PDF document only"
    return "Photo (JPG, PNG) or PDF"


def parse_requirements(raw: list[dict] | None) -> list[JoinDocumentRequirement]:
    if not raw:
        return []
    out: list[JoinDocumentRequirement] = []
    for i, item in enumerate(raw[:_MAX_SLOTS]):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            raise HTTPException(
                status_code=400,
                detail=f"Document #{i + 1} needs a short description (e.g. 'ID card')",
            )
        kind = str(item.get("kind") or JoinDocumentKind.any.value).strip().lower()
        if kind not in {k.value for k in JoinDocumentKind}:
            raise HTTPException(
                status_code=400,
                detail=f"Document #{i + 1} has an invalid file type",
            )
        out.append(JoinDocumentRequirement(label=label[:120], kind=kind))
    return out


def normalize_requirements_payload(
    requirements: list[JoinDocumentRequirement] | None,
) -> list[dict] | None:
    if not requirements:
        return None
    if len(requirements) > _MAX_SLOTS:
        raise HTTPException(
            status_code=400,
            detail=f"At most {_MAX_SLOTS} documents can be requested",
        )
    return [r.model_dump() for r in requirements]


def validate_requirements_for_service(
    svc: ServiceItem,
    *,
    requires: bool | None,
    requirements: list[JoinDocumentRequirement] | None,
) -> tuple[bool, list[dict] | None]:
    """Return (requires_join_documents, json payload) after validation."""
    flag = svc.requires_join_documents if requires is None else requires
    reqs = requirements
    if reqs is None and svc.join_document_requirements:
        reqs = parse_requirements(svc.join_document_requirements)
    payload = normalize_requirements_payload(reqs)
    if flag and not payload:
        raise HTTPException(
            status_code=400,
            detail="Add at least one document requirement or turn off document requests",
        )
    if not flag:
        payload = None
    return flag, payload


def _mime_allowed(content_type: str, kind: str) -> bool:
    ct = (content_type or "").split(";")[0].strip().lower()
    if kind == JoinDocumentKind.image.value:
        return ct in _IMAGE_MIMES
    if kind == JoinDocumentKind.pdf.value:
        return ct in _PDF_MIMES
    return ct in _IMAGE_MIMES or ct in _PDF_MIMES


async def read_upload(upload: UploadFile) -> tuple[str, str, bytes]:
    raw_name = upload.filename or "document"
    content_type = (upload.content_type or "application/octet-stream").split(";")[0].strip().lower()
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    return raw_name, content_type, data


def assert_join_documents_ready(
    svc: ServiceItem,
    uploads: list[UploadFile] | None,
) -> list[JoinDocumentRequirement]:
    reqs = parse_requirements(svc.join_document_requirements)
    if not svc.requires_join_documents:
        if uploads:
            raise HTTPException(
                status_code=400,
                detail="This line does not ask for documents",
            )
        return []
    if not reqs:
        raise HTTPException(
            status_code=500,
            detail="Document rules are misconfigured for this line",
        )
    if not uploads or len(uploads) != len(reqs):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Please upload {len(reqs)} file(s): "
                + ", ".join(f"{r.label} ({kind_label(r.kind)})" for r in reqs)
            ),
        )
    return reqs


async def store_ticket_join_documents(
    session: Session,
    *,
    ticket_id: uuid.UUID,
    service_item_id: uuid.UUID,
    requirements: list[JoinDocumentRequirement],
    uploads: list[UploadFile],
) -> list[TicketJoinDocument]:
    rows: list[TicketJoinDocument] = []
    folder = f"{settings.CLOUDINARY_FOLDER}/join-docs/{service_item_id}"

    for idx, (req, upload) in enumerate(zip(requirements, uploads, strict=True)):
        raw_name, content_type, data = await read_upload(upload)
        if not _mime_allowed(content_type, req.kind):
            raise HTTPException(
                status_code=400,
                detail=(
                    f'"{req.label}" must be {kind_label(req.kind).lower()}. '
                    f"You uploaded {content_type or 'unknown type'}."
                ),
            )
        stored = cloudinary_storage.upload_bytes(
            data=data,
            filename=kyc_docs._safe_filename(raw_name),
            folder=folder,
        )
        row = TicketJoinDocument(
            ticket_id=ticket_id,
            slot_index=idx,
            label=req.label,
            kind=req.kind,
            filename=raw_name[:255],
            content_type=content_type[:120],
            storage_relpath=stored.public_id,
            resource_type=stored.resource_type[:16],
        )
        session.add(row)
        rows.append(row)
    session.commit()
    for row in rows:
        session.refresh(row)
    return rows


def list_ticket_join_documents(
    session: Session, *, ticket_id: uuid.UUID
) -> list[TicketJoinDocumentPublic]:
    rows = list(
        session.exec(
            select(TicketJoinDocument)
            .where(TicketJoinDocument.ticket_id == ticket_id)
            .order_by(TicketJoinDocument.slot_index)
        ).all()
    )
    return [document_public(r) for r in rows]


def document_public(row: TicketJoinDocument) -> TicketJoinDocumentPublic:
    url = cloudinary_storage.signed_delivery_url(
        public_id=row.storage_relpath,
        resource_type=row.resource_type,
    )
    return TicketJoinDocumentPublic(
        id=row.id,
        ticket_id=row.ticket_id,
        slot_index=row.slot_index,
        label=row.label,
        kind=row.kind,
        filename=row.filename,
        content_type=row.content_type,
        created_at=row.created_at,
        download_url=url,
    )


def requirements_for_public(svc: ServiceItem) -> list[dict[str, Any]]:
    if not svc.requires_join_documents:
        return []
    return [
        {
            "label": r.label,
            "kind": r.kind,
            "kind_hint": kind_label(r.kind),
        }
        for r in parse_requirements(svc.join_document_requirements)
    ]
