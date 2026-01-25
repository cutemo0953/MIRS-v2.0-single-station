# xIRS Update Server Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY main.py .

# Create data directory
RUN mkdir -p /app/data/releases

# Environment
ENV UPDATE_SERVER_DATA=/app/data
ENV UPDATE_SERVER_ADMIN_KEY=change-me-in-production

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
