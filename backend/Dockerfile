# Backend image (FastAPI + LLM parser).
#
# The optional Whisper audio layer pulls in PyTorch (~2GB) and needs ffmpeg, which is too
# large for most free tiers, so it is gated behind a build arg and off by default:
#
#   docker build -t orchestrator-backend .                       # core (no audio)
#   docker build --build-arg INSTALL_AUDIO=true -t ... .         # with Whisper STT
FROM python:3.11-slim

ARG INSTALL_AUDIO=false
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt requirements-audio.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    if [ "$INSTALL_AUDIO" = "true" ]; then \
        apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
        rm -rf /var/lib/apt/lists/* && \
        pip install --no-cache-dir -r requirements-audio.txt ; \
    fi

COPY app ./app

EXPOSE 8000

# Render and most PaaS inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
