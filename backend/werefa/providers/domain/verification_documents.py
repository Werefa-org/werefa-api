"""KYC document kinds and required sets for provider verification."""

from werefa.shared.enums import ProviderDocumentKind

# Minimum documents every business must upload before admin can approve.
REQUIRED_VERIFICATION_KINDS: tuple[str, ...] = (
    ProviderDocumentKind.trade_license.value,
    ProviderDocumentKind.owner_id.value,
    ProviderDocumentKind.address_proof.value,
)

KIND_LABELS: dict[str, str] = {
    ProviderDocumentKind.trade_license.value: "Trade / business license",
    ProviderDocumentKind.owner_id.value: "Owner ID (national ID or passport)",
    ProviderDocumentKind.address_proof.value: "Proof of address",
    ProviderDocumentKind.health_permit.value: "Health / sanitation permit",
    ProviderDocumentKind.establishment_letter.value: "Official establishment letter",
    ProviderDocumentKind.tin_certificate.value: "TIN certificate",
    ProviderDocumentKind.other.value: "Other supporting document",
}

UPLOADABLE_KINDS: tuple[str, ...] = tuple(KIND_LABELS.keys())


def infer_kind_from_filename(filename: str) -> str | None:
    """Map legacy ``[License] file.pdf`` uploads to document kinds."""
    import re

    match = re.match(r"^\[(License|Permit|Insurance|Other)\]\s*", filename, re.I)
    if not match:
        return None
    label = match.group(1).lower()
    legacy = {
        "license": ProviderDocumentKind.trade_license.value,
        "permit": ProviderDocumentKind.health_permit.value,
        "insurance": ProviderDocumentKind.other.value,
        "other": ProviderDocumentKind.other.value,
    }
    return legacy.get(label)


def normalize_document_kind(raw: str) -> str:
    value = (raw or "").strip().lower().replace("-", "_")
    if value in UPLOADABLE_KINDS:
        return value
    legacy = {
        "license": ProviderDocumentKind.trade_license.value,
        "permit": ProviderDocumentKind.health_permit.value,
        "insurance": ProviderDocumentKind.other.value,
    }
    if value in legacy:
        return legacy[value]
    raise ValueError(
        f"Invalid document kind. Allowed: {', '.join(UPLOADABLE_KINDS)}"
    )
