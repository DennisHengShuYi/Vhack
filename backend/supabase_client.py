"""
Singleton Supabase client — shared by mission_flusher.py and history.py.
Reads SUPABASE_URL and SUPABASE_ANON_KEY from environment.
"""
import os
from supabase import create_client, Client

_client: Client | None = None


def get_client() -> Client:
    """Return shared Supabase client, creating it on first call."""
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_ANON_KEY", "")
        if not url or not key:
            raise EnvironmentError(
                "SUPABASE_URL and SUPABASE_ANON_KEY must be set in environment"
            )
        _client = create_client(url, key)
    return _client
