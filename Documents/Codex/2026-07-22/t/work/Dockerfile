FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY main.py sources.json README.md /app/

CMD ["python", "main.py", "run", "--mode", "both"]
