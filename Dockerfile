# Use a lightweight Python 3.14 image as the base.
FROM python:3.14-slim

# PERF-03: number of Uvicorn worker processes. Uvicorn reads WEB_CONCURRENCY when --workers is not given, so the CMD stays free of it and the value can be
# changed from .env / docker-compose without rebuilding. Use 2 to 4 depending on the CPUs of the host (4 measured: GET /tasks 934 -> 1,687 req/s).
# It needs OPT-05 (WAL, so that several processes can use SQLite at once).
# KNOWN LIMIT: the login/register rate limit lives in each process's memory, so the real limit is (limit x workers) until it is shared (see docs/PERF-03-*.md).
ENV WEB_CONCURRENCY=4

# Set the working directory inside the container.
WORKDIR /app

# Copy the dependency list and install required Python packages.
# Disable pip caching to reduce unnecessary image size.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source code into the container.
COPY . .

# Create a non-root user and grant ownership of the SQLite data directory.
RUN useradd -m -u 1000 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

# Document the port used by the FastAPI application.
EXPOSE 8000

# Start the FastAPI application using Uvicorn.
# Listen on all network interfaces to allow external connections.
#
# SEG-02: behind Nginx every request comes from Nginx's own IP. With
# --proxy-headers, Uvicorn takes the client IP from X-Forwarded-For, but only
# when the request comes from an address in --forwarded-allow-ips. That list is
# the compose network (a fixed subnet, declared in docker-compose.yml: keep both
# values equal; tests/test_seg02_proxy_config.py checks it). Never use "*": any
# client that reached the port could then forge its IP.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=10.250.250.0/24"]
