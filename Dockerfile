FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Run as a non-root user
RUN useradd --create-home --uid 1000 otto

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py storage.py ./

# State lives in /app/data — mount a volume here to persist events.json
RUN mkdir -p /app/data && chown -R otto:otto /app
USER otto

VOLUME ["/app/data"]

CMD ["python", "bot.py"]
