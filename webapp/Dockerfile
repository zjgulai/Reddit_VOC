FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src:/app \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright \
    REDDIT_VOC_CHROMIUM_PATH=/usr/bin/chromium \
    REDDIT_VOC_WEB_HOST=0.0.0.0 \
    REDDIT_VOC_WEB_PORT=8080 \
    REDDIT_VOC_SITE_ROOT=/app \
    REDDIT_VOC_DATA_DIR=/app/data \
    REDDIT_VOC_OUTPUT_DIR=/app/outputs \
    REDDIT_VOC_CONFIG_DIR=/app/config \
    REDDIT_VOC_DOCS_DIR=/app/docs

RUN sed -i 's|http://deb.debian.org/debian|http://mirrors.cloud.tencent.com/debian|g; s|http://deb.debian.org/debian-security|http://mirrors.cloud.tencent.com/debian-security|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends fonts-wqy-microhei fontconfig chromium \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --timeout 60 --retries 3 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    Pillow openpyxl playwright

RUN python -m playwright install chromium

COPY webapp /app/webapp
COPY src /app/src
COPY scripts /app/scripts
COPY config /app/config
COPY docs /app/docs
COPY .env.example README.md pyproject.toml /app/
RUN mkdir -p /app/data /app/outputs /app/logs

EXPOSE 8080

CMD ["python", "-m", "webapp.app"]
