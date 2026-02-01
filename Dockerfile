FROM python:3.12-slim

# Install dependencies
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY *.py .
COPY static ./static

# Create data and logs directories
RUN mkdir -p /data /app/logs

# Expose web port
EXPOSE 5000

# Set environment defaults
ENV FLASK_HOST=0.0.0.0 \
    FLASK_PORT=5000 \
    DB_PATH=/data/wishlist.db \
    WISHLIST_FILE=/data/wishlist.txt

# Start all services
CMD ["python", "run_all.py"]
