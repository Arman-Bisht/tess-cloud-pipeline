FROM python:3.11-slim

# Allow statements and log messages to immediately appear in the Knative logs
ENV PYTHONUNBUFFERED True

WORKDIR /app

# Install system dependencies (needed for matplotlib and scientific libraries)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run the web service on container startup using functions-framework
# Port is provided by Cloud Run via PORT environment variable
CMD exec functions-framework --target=serverless_entry --port=$PORT
