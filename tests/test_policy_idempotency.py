"""IdempotencyStore — SQLite-backed cache for mutating-tool replays."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from mt5_mcp.policy.idempotency import IdempotencyStore


@pytest.fixture
def store(tmp_path: Path) -> IdempotencyStore:
    s = IdempotencyStore(path=tmp_path / "idem.db", ttl_seconds=3600)
    yield s
    s.close()


def test_no_key_no_cache(store: IdempotencyStore):
    # Without a key, lookup returns None and put is a no-op.
    assert store.lookup(key=None, action="place_order", request_hash="abc") is None
    store.put(key=None, action="place_order", request_hash="abc",
              result_json='{"ticket":1}')
    assert store.lookup(key=None, action="place_order", request_hash="abc") is None


def test_fresh_put_then_replay(store: IdempotencyStore):
    store.put(key="k1", action="place_order", request_hash="hash-1",
              result_json='{"ticket":42,"replayed":false}')
    hit = store.lookup(key="k1", action="place_order", request_hash="hash-1")
    assert hit == ("hit", '{"ticket":42,"replayed":false}')


def test_same_key_different_hash_is_divergent(store: IdempotencyStore):
    store.put(key="k1", action="place_order", request_hash="hash-1",
              result_json='{"ticket":42}')
    hit = store.lookup(key="k1", action="place_order", request_hash="hash-2")
    assert hit == ("diverged", None)


def test_lookup_evicts_expired_entries(tmp_path: Path):
    s = IdempotencyStore(path=tmp_path / "idem.db", ttl_seconds=1)
    s.put(key="k1", action="place_order", request_hash="hash-1",
          result_json='{"ticket":42}')
    time.sleep(1.1)
    # Expired — lookup returns None and the row is deleted in-band.
    assert s.lookup(key="k1", action="place_order", request_hash="hash-1") is None
    # Re-inserting under the same key is allowed (the old row is gone).
    s.put(key="k1", action="place_order", request_hash="hash-2",
          result_json='{"ticket":99}')
    assert s.lookup(key="k1", action="place_order", request_hash="hash-2") \
           == ("hit", '{"ticket":99}')
    s.close()


def test_lookup_scope_is_action_specific(store: IdempotencyStore):
    # Same key on a different action is not a match — actions partition the namespace.
    store.put(key="k1", action="place_order", request_hash="hash-1",
              result_json='{"ticket":42}')
    assert store.lookup(key="k1", action="close_position", request_hash="hash-1") is None


def test_persists_across_reopen(tmp_path: Path):
    p = tmp_path / "idem.db"
    s1 = IdempotencyStore(path=p, ttl_seconds=3600)
    s1.put(key="k1", action="place_order", request_hash="hash-1",
           result_json='{"ticket":42}')
    s1.close()
    s2 = IdempotencyStore(path=p, ttl_seconds=3600)
    assert s2.lookup(key="k1", action="place_order", request_hash="hash-1") \
           == ("hit", '{"ticket":42}')
    s2.close()


def test_put_does_not_overwrite_existing_unexpired_entry(store: IdempotencyStore):
    """First-write-wins: a divergent put for an active key is silently ignored.

    Protects against a scenario where the engine bug-puts a second entry
    after a successful first execute, which would destroy the original
    cached result and break replay for any agent still holding the key.
    """
    store.put(key="k1", action="place_order", request_hash="hash-1",
              result_json='{"ticket":42}')
    # Second put with same key but different hash — must be a no-op.
    store.put(key="k1", action="place_order", request_hash="hash-2",
              result_json='{"ticket":99}')
    # Original entry survives.
    assert store.lookup(key="k1", action="place_order", request_hash="hash-1") \
           == ("hit", '{"ticket":42}')


def test_put_same_hash_is_idempotent(store: IdempotencyStore):
    """Re-putting the same key+hash silently succeeds (no-op replay)."""
    store.put(key="k1", action="place_order", request_hash="hash-1",
              result_json='{"ticket":42}')
    store.put(key="k1", action="place_order", request_hash="hash-1",
              result_json='{"ticket":42}')
    assert store.lookup(key="k1", action="place_order", request_hash="hash-1") \
           == ("hit", '{"ticket":42}')


def test_close_is_idempotent(tmp_path):
    s = IdempotencyStore(path=tmp_path / "idem.db", ttl_seconds=3600)
    s.close()
    s.close()  # must not raise
