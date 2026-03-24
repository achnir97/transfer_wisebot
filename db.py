"""
db.py — Supabase client singleton
===================================
Import get_db() wherever you need database access.
"""

import os
import logging
from typing import Optional
from supabase import create_client, Client

logger  = logging.getLogger(__name__)
_client: Optional[Client] = None


def get_db() -> Client:
    """Return the shared Supabase client, creating it on first call."""
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in your environment."
            )
        _client = create_client(url, key)
        logger.info("Supabase client initialised")
    return _client
