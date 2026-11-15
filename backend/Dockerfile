# syntax=docker/dockerfile:1

FROM python:3.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# uv agiliza la instalación de dependencias (mismo gestor que en local).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Se copian el proyecto y el código antes del install editable para que
# setuptools encuentre el paquete `src`.
COPY pyproject.toml ./
COPY src ./src
RUN uv pip install --system --no-cache -e .

# Resto del backend: migraciones de Alembic y pruebas.
COPY . .

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
