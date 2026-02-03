FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install build dependencies needed by some Python packages
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app
RUN mkdir -p /app/sessions

EXPOSE 8000

# Run the project entrypoint which starts both worker and api
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
