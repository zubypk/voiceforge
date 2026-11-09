FROM python:3.12-slim

# Fonts for slide text. fonts-noto-core covers Arabic, Hebrew, Devanagari, Thai, Cyrillic, Greek...
# Build with --build-arg INSTALL_CJK=1 to add Chinese/Japanese/Korean slide text.
ARG INSTALL_CJK=0
RUN apt-get update \
 && apt-get install -y --no-install-recommends fontconfig fonts-dejavu-core fonts-noto-core \
 && if [ "$INSTALL_CJK" = "1" ]; then apt-get install -y --no-install-recommends fonts-noto-cjk; fi \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt   # includes imageio-ffmpeg (bundled ffmpeg binary)
COPY . .

RUN useradd --create-home app && mkdir -p /data && chown app /data
USER app
ENV PORT=8080 VF_DATA=/data
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8080'))"
CMD ["sh", "-c", "gunicorn -w 2 --threads 4 --timeout 180 -b 0.0.0.0:${PORT} app:app"]
