FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY web ./web

RUN pip install --upgrade pip && pip install .

RUN mkdir -p /app/data && useradd --create-home --uid 10001 secondbrain \
    && chown -R secondbrain:secondbrain /app
USER secondbrain

EXPOSE 8000

CMD ["python", "-m", "app"]
