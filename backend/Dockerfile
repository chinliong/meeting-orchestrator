# Backend image (FastAPI + LLM parser).
#
# ffmpeg is installed in the base layer: the hosted Whisper path uses it to compress/transcode
# uploads (and strip video) down to a size the transcription API accepts. It's a lightweight
# native binary — unrelated to the heavy local-Whisper layer below.
#
# The optional *local* Whisper layer additionally pulls in PyTorch (~2GB), which is too large
# for most free tiers, so it stays gated behind a build arg and off by default:
#
#   docker build -t orchestrator-backend .                       # core (hosted STT only)
#   docker build --build-arg INSTALL_AUDIO=true -t ... .         # + local Whisper model
FROM python:3.11-slim

ARG INSTALL_AUDIO=false
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-audio.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    if [ "$INSTALL_AUDIO" = "true" ]; then \
        pip install --no-cache-dir -r requirements-audio.txt ; \
    fi

COPY app ./app

EXPOSE 8000

# Render and most PaaS inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
