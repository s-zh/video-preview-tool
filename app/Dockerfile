ARG BASE_IMAGE=python:3.11-slim
FROM $BASE_IMAGE

ARG APT_MIRROR
RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
        sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list; \
    fi && \
    apt-get update && \
    apt-get install -y ffmpeg intel-media-va-driver mesa-va-drivers libva2 libva-drm2 libva-dev fonts-dejavu-core fontconfig && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
ARG PIP_INDEX
RUN if [ -n "$PIP_INDEX" ]; then \
        pip install --no-cache-dir -r requirements.txt -i "$PIP_INDEX"; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

COPY . .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
