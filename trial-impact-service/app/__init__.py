"""Application factory for the trial-impact service.

``create_app`` wires together configuration, the SQLite database, the Devin
client, the market-alert fan-out, and the ticker map, registering them on
``app.extensions["trial_impact"]`` so route handlers (and tests) can retrieve
them without module-level globals.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Flask

from .alerts import Alerter
from .config import Config
from .db import Database
from .devin_client import DevinClient
from .market_model import load_tickers
from .routes import bp


def create_app(config: Config | None = None, **overrides: Any) -> Flask:
    """Build and configure the Flask app.

    Parameters
    ----------
    config:
        A :class:`Config` instance. Defaults to one built from the environment.
    overrides:
        Optional keyword overrides for the registered collaborators (``db``,
        ``devin``, ``alerter``, ``tickers``). Tests use these to inject fakes.
    """
    cfg = config or Config.from_env()
    app = Flask(__name__)

    database = overrides.get("db") or Database(cfg.database_path)
    devin = overrides.get("devin") or DevinClient(
        api_key=cfg.devin_api_key, api_base=cfg.devin_api_base
    )
    alerter = overrides.get("alerter") or Alerter(cfg)
    tickers = overrides.get("tickers")
    if tickers is None:
        tickers = load_tickers(cfg.tickers_path)

    app.extensions["trial_impact"] = {
        "config": cfg,
        "db": database,
        "devin": devin,
        "alerter": alerter,
        "tickers": tickers,
    }

    # Webhook signature verification is keyed off the presence of the shared secret, so
    # an unset WATCHER_SHARED_SECRET silently accepts *any* caller's trial event — each
    # of which spends a Devin session. That default is deliberate (the demos and local
    # runs post unsigned), but it must never be quiet: an operator who forgets the
    # secret in production would otherwise get an open endpoint and no indication of it.
    if not cfg.signature_required:
        logging.getLogger(__name__).warning(
            "WATCHER_SHARED_SECRET is not set: webhook signature verification is "
            "DISABLED and /webhook/trial-update will accept unsigned requests from "
            "anyone. Set it for any non-local deployment."
        )

    app.register_blueprint(bp)
    return app
