FROM python:3.11-slim-bookworm

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    icecast2 \
    liquidsoap \
    ffmpeg \
    nginx \
    curl \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY static/ ./static/
COPY templates/ ./templates/
COPY config/ ./config/
COPY entrypoint.sh .

# Create necessary directories
RUN mkdir -p /media/music /media/promos /media/jingles /media/ads \
    /media/random-moderation /media/planned-moderation /media/musicbeds \
    /data /var/log/icecast2 /var/log/liquidsoap /var/log/supervisor

# Copy configuration files
COPY config/icecast.xml /etc/icecast2/icecast.xml
COPY config/nginx.conf /etc/nginx/nginx.conf
COPY config/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Set permissions
RUN chown -R www-data:www-data /var/log/icecast2 && \
    chown -R nobody:nogroup /var/log/icecast2 && \
    chmod +x entrypoint.sh

# Expose ports
EXPOSE 8080 8000 9999

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
