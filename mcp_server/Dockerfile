# Use the official Python image
FROM python:3.13-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set workign directory
WORKDIR /app

COPY pyproject.toml ./
COPY server.py ./

# Allow statements and log messages to immediately appear in the logs
ENV PYTHONUNBUFFERED=1

# Install dependencies
RUN uv venv && uv pip install -e .

EXPOSE 3200

# Run the FastMCP server
CMD ["python", "server.py"]