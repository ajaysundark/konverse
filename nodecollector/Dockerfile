FROM golang:latest

WORKDIR /app

# Copy module files and download dependencies first to leverage Docker cache
COPY go.mod go.sum ./
RUN go mod download

# Copy the rest of the application source code
COPY . .

# Build the application binary
RUN go build -o /app/nodecollector ./cmd

# Expose the port the server listens on
EXPOSE 3100

# Set the entrypoint to run the application
ENTRYPOINT ["/app/nodecollector"]