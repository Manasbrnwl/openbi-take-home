# Single image: builds the warehouse at image build time, serves API + frontend read-only.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    NB_WAREHOUSE=/srv/warehouse/northbeam.duckdb
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY northbeam_ats_pack/ northbeam_ats_pack/
COPY pipeline/ pipeline/
COPY metrics/ metrics/
RUN python -m pipeline.run

COPY app/ app/
COPY frontend/ frontend/

# Run as an unprivileged user; the warehouse is read-only at runtime.
RUN useradd --system --uid 10001 nb && chmod -R a-w /srv/warehouse
USER nb

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
