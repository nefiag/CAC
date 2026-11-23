FROM python:3.11-slim
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
ARG DEBIAN_MIRROR=https://mirrors.cloud.tencent.com
RUN sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR}|g; s|http://deb.debian.org/debian-security|${DEBIAN_MIRROR}/debian-security|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.txt

COPY . .
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=*"]
