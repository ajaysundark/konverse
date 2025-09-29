# Konverse

Konverse is an in-cluster intelligent agent for Kubernetes cluster management, designed to act as an SRE's sidekick. It provides deep insights into node and workload health, helping diagnose performance issues and maintain cluster stability.

## Architecture

Konverse's architecture is designed for comprehensive, real-time analysis of Kubernetes nodes. It combines efficient data collection with powerful AI-driven analysis to provide actionable insights.

*   **MCP Server (`mcp_server`):** This is the intelligence core of Konverse. It's a Python-based server that exposes an API for an external Large Language Model (LLM), such as Google's Gemini. The server defines a set of tools the LLM can use to gather and analyze data from the Konverse Agent. This allows an SRE to interact with the cluster in natural language, asking the LLM to diagnose complex issues like node memory pressure or performance degradation. The server is located in the `mcp_server/` directory.

*   **Konverse Agent (`nodecollector`):** A lightweight agent written in Go that runs as a DaemonSet on each node in the cluster. It collects a continuous stream of node-level metrics, including CPU, memory, swap utilization, and disk I/O. The agent is located in the `nodecollector/` directory.

*   **eBPF Tools (`ebpf-tools`):** A collection of powerful eBPF tracers for efficient, low-overhead sourcing of critical kernel-level events. These tools can capture events like OOM kills and high-latency swap faults, providing granular data that is crucial for debugging complex performance problems. The collected events are sent to the Konverse Agent for aggregation. The tools are located in the `ebpf-tools/` directory.

## Getting Started

### Building the Agent Docker Image

The Konverse agent is containerized using the provided `nodecollector/Dockerfile`.

1.  **Navigate to the `nodecollector` directory:**
    ```bash
    cd nodecollector
    ```

2.  **Build the Docker image:** Replace `<your-registry>` with your container registry path.
    ```bash
    docker build -t <your-registry>/konverse/nodecollector:v0.1 .
    ```

3.  **Push the image to your container registry:**
    ```bash
    docker push <your-registry>/konverse/nodecollector:v0.1
    ```

### Deployment

The Konverse agent is deployed as a Kubernetes DaemonSet to ensure it runs on every node in the cluster.

1.  **Update the image in the deployment file:** Make sure the `image` field in `deploy/k8s-hack.yml` points to the image you just pushed.

2.  **Apply the manifest:**
    ```bash
    kubectl apply -f deploy/k8s-hack.yml
    ```

## Konverse Agent API

The agent exposes two ports for different purposes.

### Query API (Port 3100)

This API is for querying collected metrics. To access it, you can port-forward from one of the agent pods:

```bash
# Find a pod name
kubectl get pods -n kube-system | grep node-debugger

# Port-forward
kubectl port-forward <pod-name> -n kube-system 3100:3100
```

**Endpoints:**

*   `GET /ping`: A simple health check endpoint that returns `"ok"`.
    *   **Example:** `curl http://127.0.0.1:3100/ping`

*   `GET /history`: Returns a JSON array of the last 15 minutes of node vmstat data.
    *   **Example:** `curl http://127.0.0.1:3100/history`

*   `GET /stream`: Streams live node vmstat data using Server-Sent Events (SSE).
    *   **Example:** `curl -N -H "Accept: text/event-stream" http://127.0.0.1:3100/stream`

### Ingestion API (Port 3101)

This API is used by the eBPF tools to send events to the agent.

*   `POST /events`: Ingests events (e.g., OOM kills, container lifecycle events) from the eBPF tracers. The event is sent as a JSON payload in the request body.
