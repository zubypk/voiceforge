FROM python:3.12-slim

# Fonts for slide text. fonts-noto-core covers Arabic, Hebrew, Devanagari, Thai, Cyrillic, Greek...
# Build with --build-arg INSTALL_CJK=1 to add Chinese/Japanese/Korean slide text.
# LibreOffice (Writer, Calc, Impress) converts Word/Excel/PowerPoint to slides; build with --build-arg INSTALL_OFFICE=0
# for a smaller image (PDF import still works; .pptx/.docx fall back to editable text scenes).
ARG INSTALL_CJK=0
ARG INSTALL_OFFICE=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends fontconfig fonts-dejavu-core fonts-noto-core \
 && if [ "$INSTALL_CJK" = "1" ]; then apt-get install -y --no-install-recommends fonts-noto-cjk; fi \
 && if [ "$INSTALL_OFFICE" = "1" ]; then apt-get install -y --no-install-recommends libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui \
      || apt-get install -y --no-install-recommends libreoffice-writer libreoffice-calc libreoffice-impress; fi \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt   # includes imageio-ffmpeg (bundled ffmpeg binary)
COPY . .

RUN useradd --create-home app && mkdir -p /data && chown app /data
USER app
ENV PORT=8080 VF_DATA=/data HOME=/tmp PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8080'))"
CMD ["sh", "-c", "gunicorn -w ${WORKERS:-2} --threads 4 --timeout 600 -b 0.0.0.0:${PORT} app:app"]
