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

    # The webhook fails *closed*: with no shared secret there is no way to authenticate
    # a caller, and each accepted event spends a Devin session, so /webhook/trial-update
    # rejects *every* request (503) until WATCHER_SHARED_SECRET is set. Warn loudly at
    # startup so a misconfigured deployment is obvious (a dark endpoint) rather than
    # silently open to anyone — the failure the old fail-open default risked (issue #8).
    if not cfg.signature_required:
        logging.getLogger(__name__).warning(
            "WATCHER_SHARED_SECRET is not set: /webhook/trial-update is DISABLED and "
            "fails closed (returns 503 to every caller). Set it to accept signed "
            "trial events."
        )

    app.register_blueprint(bp)
    return app
