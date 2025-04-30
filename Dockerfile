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

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir gunicorn

# Copy project files
COPY . /app/

# Make port available to the world outside this container
EXPOSE 8000

# Set the startup command to run your application using JSON array format
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--timeout", "1000", "--worker-class", "aiohttp.worker.GunicornWebWorker", "app:APP"]