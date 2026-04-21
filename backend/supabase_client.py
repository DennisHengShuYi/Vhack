"""
Singleton Supabase client — shared by mission_flusher.py and history.py.
Reads SUPABASE_URL and SUPABASE_ANON_KEY from environment.
"""
import os
import sys
import threading
from typing import Optional, Any

try:
    from supabase import create_client, Client
    _SUPABASE_AVAILABLE = True
except ImportError:
    Client = Any
    _SUPABASE_AVAILABLE = False

_client: Optional[Client] = None
_lock = threading.Lock()

class MockSupabaseQuery:
    def __getattr__(self, name):
        def method(*args, **kwargs):
            return self
        return method
    
    def execute(self):
        class MockResult:
            data = []
        return MockResult()

class MockSupabaseClient:
    def table(self, table_name):
        return MockSupabaseQuery()

def get_client() -> Client:
    """Return shared Supabase client or a mock if Supabase is not installed."""
    global _client
    if not _SUPABASE_AVAILABLE:
        if _client is None:
            print("[FLUSH] Supabase package not found — skipping database sync", file=sys.stderr)
            _client = MockSupabaseClient()
        return _client

    if _client is None:
        with _lock:
            if _client is None:
                url = os.environ.get("SUPABASE_URL", "")
                key = os.environ.get("SUPABASE_ANON_KEY", "")
                if not url or not key:
                    raise EnvironmentError(
                        "SUPABASE_URL and SUPABASE_ANON_KEY must be set in environment"
                    )
                _client = create_client(url, key)
    return _client
