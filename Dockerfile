# Single-image deployment: the React app is built, then served by the same FastAPI
# process that serves the API. One container, one origin, no CORS.

# ---------------------------------------------------------------------------
# Stage 1 - build the frontend
# ---------------------------------------------------------------------------
FROM node:20-slim AS frontend

WORKDIR /build

# Copy the manifests first so the dependency layer is cached across source edits.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# ---------------------------------------------------------------------------
# Stage 2 - Python runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Hugging Face Spaces routes to 7860 unless told otherwise. Platforms that
    # inject their own $PORT (Railway, Cloud Run) override this at runtime.
    PORT=7860

WORKDIR /app

# xgboost links against libgomp, which the slim image does not ship.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencies before source, so a code change does not reinstall ~434 MB of wheels.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code, the dataset, and the pre-trained model artefacts.
COPY backend/ ./backend/
COPY data/ ./data/
COPY ml/ ./ml/

COPY --from=frontend /build/dist ./frontend/dist

# Run as a non-root user. UID 1000 is what Hugging Face Spaces expects, and it is a
# sensible default everywhere else.
RUN useradd --create-home --uid 1000 user \
    && chown -R user:user /app
USER user
ENV HOME=/home/user

EXPOSE 7860

CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-7860} --workers 1"]
