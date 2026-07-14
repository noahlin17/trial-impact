"""HMAC-SHA256 signing — standalone copy shared with the trial-impact service.

``sign()`` is byte-for-byte identical to ``app/signing.py`` in the trial-impact
service; the service's ``verify()`` is deliberately omitted, since a producer only
ever signs. It is duplicated here (rather than imported) so the watcher is a fully
independent, separately-deployable service with no dependency on the other repo.
Both sides must derive the signature the same way — if ``sign()`` diverges, every
webhook silently fails verification, so the two copies must be changed together.
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
