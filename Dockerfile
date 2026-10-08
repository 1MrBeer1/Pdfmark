FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-rus \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pdf2md ./pdf2md

RUN useradd --create-home --uid 10001 pdf2md
USER pdf2md

EXPOSE 8000
# JOB_STORE is process-local: conversion and download must use the same worker.
CMD ["python", "-m", "uvicorn", "pdf2md.webapp:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
