"""Feature-and-metadata ingesters for the Tier-1 backtest scaffold.

The ingesters deliberately do not adjudicate clinical outcomes. They produce
``TrialRecord`` rows with unknown outcomes until a human adds an auditable label.
"""
