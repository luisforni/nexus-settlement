FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --no-create-home appuser

FROM base AS deps
COPY requirements.txt ./
RUN pip install -r requirements.txt

FROM deps AS development
ENV ENVIRONMENT=development
COPY . .
EXPOSE 8001
USER appuser
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", \
     "--reload", "--log-level", "debug"]

FROM deps AS production
ENV ENVIRONMENT=production
COPY --chown=appuser:appgroup . .
EXPOSE 8001
USER appuser
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8001", \
     "--workers", "4", \
     "--log-config", "/dev/null", \
     "--no-access-log"]
