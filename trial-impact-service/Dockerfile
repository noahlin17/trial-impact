# Small, reproducible image for the Flask service.
FROM python:3.12-slim

# Don't write .pyc files and keep stdout/stderr unbuffered so logs stream live.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first so the layer is cached across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code.
COPY app ./app
COPY wsgi.py simulate_trial.py tickers.json ./
# The heavy simulation stack (requirements-sim.txt) is intentionally NOT installed
# here — it runs inside a Devin session, not the web service.

# SQLite lives on a mounted volume here (see docker-compose.yml).
ENV DATABASE_PATH=/data/trial_impact.db
RUN mkdir -p /data

EXPOSE 8000

# Serve with gunicorn. A single worker keeps the SQLite access model simple; the
# workload is light (webhooks + manual polls), so one worker is plenty.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--timeout", "120", "wsgi:app"]
