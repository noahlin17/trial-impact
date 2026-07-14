"""Centralised configuration for the trial-impact service.

All runtime configuration is read from environment variables so that the same
image can run in any environment without code changes (12-factor style). Secrets
(``DEVIN_API_KEY``, ``WATCHER_SHARED_SECRET``, SMTP credentials) are *never*
hard-coded — they must be supplied via the environment (see ``.env.example``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Immutable snapshot of the service configuration.

    Built once at startup via :meth:`from_env`. Keeping it frozen makes the
    configuration easy to reason about and impossible to mutate accidentally at
    request time.
    """

    # --- Devin (runs the biophysical simulation) ------------------------------
    devin_api_key: str
    devin_api_base: str
    # Repo Devin clones to run the real-physics pipeline (app/simulation.py).
    sim_repo_url: str
    # The exact commit Devin checks out before running. Pinning it is what makes a
    # run reproducible-from-source and lets `code_patched` be *verified* against the
    # commit rather than trusted. Empty is treated as "not configured": the webhook
    # refuses to launch an unpinned (unverifiable) session, the same way it refuses
    # without an API key. See prompts.py and "The result contract" in the README.
    sim_repo_commit: str

    # --- Trigger authentication ----------------------------------------------
    # Shared secret the ctgov-watcher signs webhooks with (HMAC-SHA256). When
    # empty, signature verification is skipped (dev mode only).
    watcher_shared_secret: str

    # --- Output surfaces ------------------------------------------------------
    slack_webhook_url: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    email_from: str
    email_to: str

    # --- Market model ---------------------------------------------------------
    tickers_path: str
    # |probability-of-success delta| at/above which an event is "market-moving"
    # and an alert fires.
    market_moving_threshold: float

    # --- Storage --------------------------------------------------------------
    database_path: str

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            devin_api_key=os.environ.get("DEVIN_API_KEY", ""),
            devin_api_base=os.environ.get("DEVIN_API_BASE", "https://api.devin.ai/v1"),
            sim_repo_url=os.environ.get(
                "SIM_REPO_URL", "https://github.com/noahlin17/trial-impact"
            ),
            sim_repo_commit=os.environ.get("SIM_REPO_COMMIT", ""),
            watcher_shared_secret=os.environ.get("WATCHER_SHARED_SECRET", ""),
            slack_webhook_url=os.environ.get("SLACK_WEBHOOK_URL", ""),
            smtp_host=os.environ.get("SMTP_HOST", ""),
            smtp_port=int(os.environ.get("SMTP_PORT", "587")),
            smtp_user=os.environ.get("SMTP_USER", ""),
            smtp_password=os.environ.get("SMTP_PASSWORD", ""),
            email_from=os.environ.get("EMAIL_FROM", ""),
            email_to=os.environ.get("EMAIL_TO", ""),
            tickers_path=os.environ.get("TICKERS_PATH", "tickers.json"),
            market_moving_threshold=float(
                os.environ.get("MARKET_MOVING_THRESHOLD", "0.10")
            ),
            # Default lives under /data so it can be mounted as a Docker volume
            # and survive container restarts.
            database_path=os.environ.get("DATABASE_PATH", "/data/trial_impact.db"),
        )

    @property
    def devin_configured(self) -> bool:
        return bool(self.devin_api_key)

    @property
    def sim_pinned(self) -> bool:
        """True once a commit is pinned — required to launch a verifiable session."""
        return bool(self.sim_repo_commit)

    @property
    def slack_configured(self) -> bool:
        return bool(self.slack_webhook_url)

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.email_from and self.email_to)

    @property
    def signature_required(self) -> bool:
        return bool(self.watcher_shared_secret)
