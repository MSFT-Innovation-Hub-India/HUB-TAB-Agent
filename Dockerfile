# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Set work directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt /app/

# Copy .env file for environment variables
COPY .env /app/.env

# Install dependencies in a completely fresh environment
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir gunicorn

# Copy project files (excluding files specified in .dockerignore)
# NOTE: .dockerignore should exclude all virtual environment folders
COPY . /app/

# Verify no virtual environments were copied over
RUN if [ -d ".venv" ]; then echo "Error: .venv directory exists" && exit 1; fi
RUN if [ -d "venv" ]; then echo "Error: venv directory exists" && exit 1; fi

# Make port available to the world outside this container
EXPOSE 8000

# Set the startup command to run your application using JSON array format
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--timeout", "1000", "--worker-class", "aiohttp.worker.GunicornWebWorker", "app:APP"]