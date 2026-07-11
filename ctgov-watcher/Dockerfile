# Small image for the ClinicalTrials.gov watcher.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY watcher.py signing.py watchlist.json ./

# Persist last-seen state across restarts (mount a volume at /data).
ENV STATE_PATH=/data/watcher_state.db
RUN mkdir -p /data

# Default: loop forever on POLL_INTERVAL_SECONDS. Override with `--once` for cron.
CMD ["python", "watcher.py"]
