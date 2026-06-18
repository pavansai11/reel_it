# ReelMagic backend image (serves both the API and the RQ worker -- pick via CMD).
FROM python:3.11-slim

# System deps: ffmpeg (render), libsndfile (librosa), fonts (overlay/watermark).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        fonts-dejavu-core \
        libglib2.0-0 \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# To enable GPU-quality CLIP/MediaPipe scoring, uncomment:
# COPY requirements-ml.txt .
# RUN pip install --no-cache-dir -r requirements-ml.txt

COPY . .

# Bake the bundled music + beat maps into the image (deterministic). Replace with
# real licensed audio by COPYing into assets/music before this step.
RUN python scripts/generate_music.py && python scripts/build_beatmaps.py

ENV ENV=production \
    PYTHONUNBUFFERED=1 \
    PORT=8000

EXPOSE 8000

# Default: API server. Override CMD to run the worker (see docker-compose).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
