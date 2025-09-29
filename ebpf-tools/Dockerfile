# Use a standard Ubuntu base image
FROM ubuntu:24.04

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies: Python, pip, requests, and BCC prerequisites
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-requests \
    python3-yaml \
    bpfcc-tools \
    && rm -rf /var/lib/apt/lists/*

# Copy your application files into the container
WORKDIR /
COPY tracers /tracers
COPY entrypoint.sh .

# Make the entrypoint script executable
RUN chmod +x /entrypoint.sh

# Set the entrypoint
ENTRYPOINT ["/entrypoint.sh"]
