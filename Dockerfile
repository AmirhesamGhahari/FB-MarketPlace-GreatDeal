FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
COPY configs/ configs/
COPY transform/ transform/

RUN pip install --no-cache-dir -e .
