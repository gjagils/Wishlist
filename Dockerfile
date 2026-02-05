# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# Dependencies apart - wordt gecached zolang requirements.txt niet wijzigt
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Applicatie bestanden (wijzigen vaker, daarom als laatste)
COPY *.py .
COPY static ./static

RUN mkdir -p /data /app/logs

EXPOSE 5000

ENV FLASK_HOST=0.0.0.0 \
    FLASK_PORT=5000 \
    DB_PATH=/data/wishlist.db \
    WISHLIST_FILE=/data/wishlist.txt

CMD ["python", "run_all.py"]
