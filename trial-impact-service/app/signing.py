"""HMAC-SHA256 signing shared by the watcher (producer) and the service (verifier).

The ctgov-watcher signs every webhook body with a shared secret and sends the
hex digest in the ``X-CTGov-Signature`` header (``sha256=<hexdigest>``). The
service recomputes the digest over the raw body and compares in constant time.

Both sides must derive the signature the *same* way, so the canonical
implementation lives here and is copied verbatim into the standalone watcher
service (which has no dependency on this package).
"""

from __future__ import annotations

import hashlib
import hmac

SIGNATURE_HEADER = "X-CTGov-Signature"
_PREFIX = "sha256="


def sign(secret: str, body: bytes) -> str:
    """Return the ``sha256=<hexdigest>`` signature for ``body``."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"{_PREFIX}{digest}"


def verify(secret: str, body: bytes, signature: str | None) -> bool:
    """Constant-time check that ``signature`` matches ``body`` under ``secret``.

    Returns ``False`` for a missing/malformed signature rather than raising, so
    callers can treat "no signature" and "wrong signature" identically.
    """
    if not signature:
        return False
    expected = sign(secret, body)
    return hmac.compare_digest(expected, signature)
