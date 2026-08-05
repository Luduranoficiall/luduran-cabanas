FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependências primeiro: essa camada só é reconstruída quando o
# requirements.txt muda, o que deixa o build do dia a dia bem mais rápido.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# O Cloud Run injeta a porta em $PORT — não fixar 8080 no código.
ENV PORT=8080
EXPOSE 8080

# Um worker só: o serviço é I/O bound (espera Gemini e Meta responderem) e o
# Cloud Run escala por instância, não por processo.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
