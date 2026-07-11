"""HMAC-SHA256 signing — standalone copy shared with the trial-impact service.

This is byte-for-byte identical to ``app/signing.py`` in the trial-impact
service. It is duplicated here (rather than imported) so the watcher is a fully
independent, separately-deployable service with no dependency on the other repo.
Both sides must derive the signature the same way.
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
