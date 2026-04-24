FROM python:3.11-slim-bookworm

WORKDIR /app

# Install Python dependencies first (layer cached unless requirements.txt changes)
COPY seo_agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Install Chromium + all OS-level dependencies via Playwright's own tooling
# This layer is cached unless the playwright version changes
RUN playwright install --with-deps chromium

# Copy application code (changes most often — kept last for cache efficiency)
COPY seo_agent/ .

# Runtime output directory (ephemeral; use a Railway volume for persistence)
RUN mkdir -p output/implementation_kit

EXPOSE 8080

# Single worker keeps the in-memory jobs dict consistent across requests.
# 8 threads handle concurrent API calls and SSE streams.
# --access-logfile - sends access logs to stdout so Railway captures them.
CMD ["sh", "-c", "exec gunicorn --workers=1 --threads=8 --timeout=300 --access-logfile - --error-logfile - --bind 0.0.0.0:${PORT:-8080} app:app"]
