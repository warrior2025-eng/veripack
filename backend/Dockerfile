# VeriPack backend image.
#
# NOTE ON PORTABILITY: this Dockerfile was written for correctness against
# a standard Debian-based Python image and standard apt package names, but
# could not actually be built or run in the sandbox this project was
# developed in (no Docker daemon available there -- see README.md's
# "Development environment note"). Build and test this yourself with
# `docker build .` before relying on it; if a package name has drifted on
# whatever Debian release the base image is pinned to, that will be the
# first thing to check.

FROM python:3.12-slim

# tesseract-ocr: the OCR engine itself (see docs/AI_PIPELINE.md for why
#   Tesseract rather than EasyOCR was used in the reference implementation).
# libgl1 / libglib2.0-0: required by opencv-python's shared library deps
#   even in headless server use -- omitting these produces an
#   "ImportError: libGL.so.1" at `import cv2` time, not at build time.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements-prod.txt backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY backend/ ./
COPY frontend/ ../frontend/

RUN mkdir -p storage/uploads storage/evidence storage/reports

ENV PORT=5000
EXPOSE 5000

# Runs the DB init + seed on first boot only if no DB file exists yet --
# see docker-entrypoint.sh. Uses gunicorn (from requirements-prod.txt) as a
# real production WSGI server rather than Flask's development server.
COPY backend/docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "main:create_app()"]
