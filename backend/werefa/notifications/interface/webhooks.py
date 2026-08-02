"""Inbound delivery receipts from the SMS gateway (FR-07).

The one endpoint here closes the loop the outbound path always left open:
``POST /messages`` tells us Twilio *took* a message, and this is where
Twilio comes back to say what the carrier did with it. Without it a text
to a disconnected number, a barred handset, or a phone that has been off
all afternoon was recorded exactly like one somebody read and acted on.

Three properties this route needs that ordinary API routes do not.

**No user, and no session cookie either.** The caller is a machine at
Twilio, so authentication is the ``X-Twilio-Signature`` HMAC and nothing
else. It is checked before the body is looked at, and a request that
fails is refused — anybody who learns this URL could otherwise mark any
customer's alert delivered, which is precisely the claim the liveness
flow now trusts when deciding whether a silent customer was warned.

**It is signed against the URL we published, not the one we received.**
Behind a proxy those differ (scheme rewritten, host swapped) and the
difference is silent: every callback simply fails to verify and every
receipt is dropped. So the URL fed to the HMAC is rebuilt from
``TWILIO_STATUS_CALLBACK_URL``, which is the string Twilio was actually
given.

**Almost everything answers 204.** Twilio retries a callback it could not
deliver, and most callbacks legitimately change nothing — the
intermediate ``sending``/``sent`` hops, duplicates, receipts for a row
that has since fallen through to another channel. Answering anything but
success for those buys a retry of a message we understood perfectly well.
Only an unverifiable signature is an error, because that one is not
Twilio asking.
"""

from __future__ import annotations

import logging
import uuid

import anyio.to_thread
from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlmodel import Session

from werefa.core.config import settings
from werefa.core.db import engine
from werefa.notifications.application import service as notifications_service
from werefa.notifications.domain.receipts import ReceiptOutcome
from werefa.notifications.infrastructure.sms import (
    RECEIPT_REFERENCE_PARAM,
    classify_status,
    validate_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["notifications"])


def _signed_url(request: Request) -> str | None:
    """Rebuild the URL Twilio signed, or ``None`` if we published none."""
    configured = (settings.TWILIO_STATUS_CALLBACK_URL or "").strip()
    if not configured:
        return None
    query = request.url.query
    return f"{configured}?{query}" if query else configured


@router.post(
    "/twilio/sms-status",
    status_code=status.HTTP_204_NO_CONTENT,
    include_in_schema=False,
    summary="Twilio SMS delivery status callback",
)
async def twilio_sms_status(*, request: Request) -> Response:
    """Record what the carrier did with one outbound text.

    ``async def`` because the raw form has to come off the wire before
    the signature can be checked over it — a sync route would have to
    let FastAPI parse named fields, and the signature covers *every*
    parameter Twilio sent, including ones we do not model.

    The ledger write therefore goes to a worker thread rather than
    running here. Twilio retries and fans out callbacks per message, so
    this is exactly the shape of traffic that would otherwise sit a
    blocking round-trip on the event loop — the stall
    ``infrastructure/delivery.py`` exists to have removed. It opens its
    own session for the same reason ``run_evaluate_smart_alerts_for_
    service_line`` does: there is no request session to hand across a
    thread boundary safely.
    """
    signed_url = _signed_url(request)
    if signed_url is None:
        # No callback URL configured means nothing was ever asked to call
        # us, so any request arriving here is unsolicited by definition.
        logger.warning("twilio_status_callback_not_configured")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        )

    form = await request.form()
    params = {str(k): str(v) for k, v in form.multi_items()}

    if not validate_signature(
        url=signed_url,
        params=params,
        signature=request.headers.get("X-Twilio-Signature"),
        auth_token=settings.TWILIO_AUTH_TOKEN,
    ):
        logger.warning(
            "twilio_status_callback_bad_signature",
            extra={"message_sid": params.get("MessageSid")},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature",
        )

    notification_id = _reference(request)
    if notification_id is None:
        # A signed callback with no row reference: a message sent by an
        # older build, or one dispatched before the id was in the URL.
        # Verified, so worth a line — but there is nothing to update.
        logger.info(
            "twilio_status_callback_unreferenced",
            extra={"message_sid": params.get("MessageSid")},
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    await anyio.to_thread.run_sync(
        _apply_receipt,
        notification_id,
        classify_status(params.get("MessageStatus")),
        params.get("MessageSid"),
        params.get("ErrorCode"),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _apply_receipt(
    notification_id: uuid.UUID,
    receipt: ReceiptOutcome,
    message_sid: str | None,
    error_code: str | None,
) -> None:
    """Ledger write, on a worker thread, in a session of its own.

    Blanket ``except``: a callback we cannot record is a receipt lost,
    which is bad — but a 500 makes Twilio replay it, and if the cause is
    the database rather than this message, the replay fails the same way
    while the retries pile up. The row keeps its pre-receipt status,
    which reads as "we never found out" and is exactly what happened.
    """
    try:
        with Session(engine) as session:
            notifications_service.record_delivery_receipt(
                session,
                notification_id=notification_id,
                receipt=receipt,
                provider_message_id=message_sid,
                error_code=error_code,
            )
    except Exception:
        logger.exception(
            "notification_receipt_not_recorded",
            extra={"notification_id": str(notification_id)},
        )


def _reference(request: Request) -> uuid.UUID | None:
    raw = request.query_params.get(RECEIPT_REFERENCE_PARAM)
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        logger.warning(
            "twilio_status_callback_bad_reference", extra={"reference": raw}
        )
        return None


__all__ = ["router"]
