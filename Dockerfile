FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Node + npm exist only to install the claude CLI, which the scheduler spawns
# per agent run. One image for scheduler and web keeps the compose file simple.
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Pinned to the version the tool-server probe was run against on the Mac
# (2026-10-09: --mcp-config + --strict-mcp-config, env passthrough, --resume).
# Treat a bump as a change: upgrade, rerun the probe, then keep it.
RUN npm install -g @anthropic-ai/claude-code@2.1.296

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY manage.py pyproject.toml ./
COPY config/ config/
COPY core/ core/
COPY scheduler/ scheduler/
COPY chat/ chat/
COPY agent/ agent/
COPY api/ api/
COPY entrypoint.sh ./

RUN DJANGO_SECRET_KEY=build-placeholder python manage.py collectstatic --noinput

ENTRYPOINT ["/bin/sh", "/app/entrypoint.sh"]
