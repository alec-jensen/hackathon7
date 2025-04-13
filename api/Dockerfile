# --- Builder Stage ---
FROM python:3.13-alpine AS builder

WORKDIR /app

# Install uv globally in the builder stage first
RUN pip install --no-cache-dir uv

# Copy dependency definition files
COPY pyproject.toml ./
# If you generate a uv.lock file, uncomment the next line
# COPY uv.lock ./

# Create the virtual environment
RUN uv venv /app/.venv

# Install dependencies using the uv from the virtual environment
# Activate the venv implicitly by calling its uv executable
RUN uv sync --no-cache

# --- Runtime Stage ---
FROM python:3.13-alpine

# Install git (needed by GitPython at runtime)
RUN apk add --no-cache git

# Add the virtual environment's bin directory to the PATH
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Copy the virtual environment with installed dependencies from the builder stage
COPY --from=builder /app/.venv /app/.venv

# Copy the application code
COPY ./api ./api

# Expose the port the app runs on
EXPOSE 8000

# Command to run the application using uvicorn
# The virtual environment is activated via the PATH modification
# Use the globally available uvicorn from the venv
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
