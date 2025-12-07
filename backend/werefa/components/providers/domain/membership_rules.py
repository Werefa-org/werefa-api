def validate_remove_last_owner(*, member_role: str, owner_count: int) -> None:
    """Ensure removing this member does not delete the last owner."""
    if member_role == "owner" and owner_count <= 1:
        raise ValueError("Provider must keep at least one owner")
