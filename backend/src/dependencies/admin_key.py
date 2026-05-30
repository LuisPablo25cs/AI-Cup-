"""FastAPI dependency that validates X-Admin-Key header for destructive operations."""

import os
import logging
from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

ADMIN_DELETE_KEY = os.getenv("ADMIN_DELETE_KEY")


async def require_admin_key(
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
) -> str:
    """Validate X-Admin-Key header against ADMIN_DELETE_KEY env var.

    Returns the valid key value on success (caller can ignore it).
    Raises 403 on missing/mismatched header, 500 if env var is unset.
    """
    if not ADMIN_DELETE_KEY:
        logger.error("ADMIN_DELETE_KEY environment variable is not set")
        raise HTTPException(
            status_code=500,
            detail="ADMIN_DELETE_KEY not configured",
        )

    if x_admin_key != ADMIN_DELETE_KEY:
        raise HTTPException(
            status_code=403,
            detail="Invalid admin key",
        )

    return x_admin_key
