# Use a lightweight Python 3.14 image as the base.
FROM python:3.14-slim

# Set the working directory inside the container.
WORKDIR /app

# Copy the dependency list and install required Python packages.
# Disable pip caching to reduce unnecessary image size.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source code into the container.
COPY . .

# Document the port used by the FastAPI application.
EXPOSE 8000

# Start the FastAPI application using Uvicorn.
# Listen on all network interfaces to allow external connections.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
