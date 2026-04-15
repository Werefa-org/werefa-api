"""Shared image upload validation."""

from __future__ import annotations

from fastapi import HTTPException, UploadFile

ALLOWED_IMAGE_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/jpg"}
)


async def read_image_upload(upload: UploadFile) -> tuple[bytes, str]:
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Invalid image type. Use JPEG, PNG, or WebP.",
        )
    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    ext = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(content_type, "jpg")
    return data, ext
