"""WSGI entrypoint.

Used by gunicorn in the container (``gunicorn wsgi:app``) and runnable directly
for local development (``python wsgi.py``).
"""

from __future__ import annotations

import os

from app import create_app

app = create_app()


if __name__ == "__main__":
    # Local development server only. In Docker the app is served by gunicorn.
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
