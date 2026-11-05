# Optional: run the importer locally in a container (docker compose run importer)
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY python-importer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY python-importer/ .
CMD ["python", "main.py"]
