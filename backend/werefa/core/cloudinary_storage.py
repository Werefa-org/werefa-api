"""Cloudinary upload and signed delivery for provider files."""

from __future__ import annotations

import os
from dataclasses import dataclass

import cloudinary
import cloudinary.uploader
import cloudinary.utils
from fastapi import HTTPException

from werefa.core.config import settings

_IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "gif"})


def _asset_public_id_name(asset_name: str) -> str:
    """Strip a trailing image extension so Cloudinary does not double-append it."""
    if "." in asset_name:
        stem, ext = asset_name.rsplit(".", 1)
        if ext.lower() in _IMAGE_EXTENSIONS:
            return stem
    return asset_name


def _delivery_public_id(public_id: str) -> str:
    """Map stored public_id to the path Cloudinary serves.

    Legacy uploads used names like ``logo.jpg`` as the public_id; delivery URLs
  then end in ``logo.jpg.jpg``. New uploads store extension-less ids (``logo``).
    """
    name = public_id.rsplit("/", 1)[-1]
    if "." in name:
        _stem, ext = name.rsplit(".", 1)
        if ext.lower() in _IMAGE_EXTENSIONS:
            return f"{public_id}.{ext.lower()}"
    return public_id


@dataclass(frozen=True)
class StoredFile:
    public_id: str
    resource_type: str
    secure_url: str


def _configure() -> None:
    if settings.CLOUDINARY_URL:
        os.environ["CLOUDINARY_URL"] = settings.CLOUDINARY_URL
        cloudinary.config(secure=True)
        return
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )


def upload_bytes(
    *,
    data: bytes,
    filename: str,
    folder: str,
) -> StoredFile:
    if not settings.cloudinary_configured:
        raise HTTPException(
            status_code=503,
            detail="Cloudinary is not configured on the server",
        )
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large (max {settings.MAX_UPLOAD_BYTES // (1024 * 1024)}MB)",
        )
    _configure()
    try:
        result = cloudinary.uploader.upload(
            data,
            folder=folder,
            public_id=None,
            resource_type="auto",
            type="authenticated",
            use_filename=True,
            unique_filename=True,
            filename_override=filename[:200] or None,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="File upload to cloud storage failed",
        ) from exc

    public_id = result.get("public_id")
    if not public_id:
        raise HTTPException(status_code=502, detail="Invalid cloud storage response")

    return StoredFile(
        public_id=public_id,
        resource_type=str(result.get("resource_type") or "raw"),
        secure_url=str(result.get("secure_url") or ""),
    )


def upload_public_image(
    *,
    data: bytes,
    folder: str,
    asset_name: str = "avatar",
) -> StoredFile:
    """Profile images — public CDN URLs (overwrite same asset name)."""
    if not settings.cloudinary_configured:
        raise HTTPException(
            status_code=503,
            detail="Cloudinary is not configured on the server",
        )
    if len(data) > settings.MAX_AVATAR_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Image too large (max {settings.MAX_AVATAR_BYTES // (1024 * 1024)}MB)",
        )
    _configure()
    try:
        result = cloudinary.uploader.upload(
            data,
            folder=folder,
            public_id=_asset_public_id_name(asset_name),
            resource_type="image",
            overwrite=True,
            invalidate=True,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Image upload to cloud storage failed",
        ) from exc

    public_id = result.get("public_id")
    if not public_id:
        raise HTTPException(status_code=502, detail="Invalid cloud storage response")

    return StoredFile(
        public_id=public_id,
        resource_type=str(result.get("resource_type") or "image"),
        secure_url=str(result.get("secure_url") or ""),
    )


def public_image_url(*, public_id: str, resource_type: str = "image") -> str:
    if not settings.cloudinary_configured:
        raise HTTPException(
            status_code=503,
            detail="Cloudinary is not configured on the server",
        )
    _configure()
    delivery_id = _delivery_public_id(public_id)
    return cloudinary.CloudinaryImage(delivery_id).build_url(
        secure=True,
        resource_type=resource_type,
    )


def delivery_url(*, public_id: str, resource_type: str) -> str:
    """Signed URL for authenticated (private) uploads."""
    if not settings.cloudinary_configured:
        raise HTTPException(
            status_code=503,
            detail="Cloudinary is not configured on the server",
        )
    _configure()
    rt = resource_type if resource_type in ("image", "video", "raw") else "raw"
    result = cloudinary.utils.cloudinary_url(
        public_id,
        resource_type=rt,
        type="authenticated",
        sign_url=True,
        secure=True,
    )
    if isinstance(result, tuple):
        return str(result[0])
    return str(result)


def signed_delivery_url(*, public_id: str, resource_type: str) -> str:
    """Alias for :func:`delivery_url` (join documents, KYC files)."""
    return delivery_url(public_id=public_id, resource_type=resource_type)
