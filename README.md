# Node Collector

`nodecollector` is a simple service that runs on each K8s node and collects
vmstat metrics like CPU, memory, swap, and disk I/O. It exposes these metrics
via an HTTP API.

## Building the Docker Image

The service is containerized using the provided `nodecollector/Dockerfile`.

1.  **Navigate to the `nodecollector` directory:** `cd
    experimental/users/ajaysundar/node-debugger/nodecollector`

2.  **Build the Docker image:** Replace the tag with your desired image name and
    version. `docker build -t
    gcr.io/ajaysundar-gke-multi-cloud-dev/hack/nodecollector:v0.1 .`

3.  **Push the image to a container registry:** `docker push
    gcr.io/ajaysundar-gke-multi-cloud-dev/hack/nodecollector:v0.1`

Note: Use your valid gcr registry path above.

## Deployment

The `nodecollector` is deployed as a Kubernetes DaemonSet to ensure it runs on
every node in the cluster.

1.  **Update the image in the deployment file:** Make sure the `image` field in
    `deploy/k8s-hack.yml` points to the image you just pushed.

2.  **Apply the manifest:** `kubectl apply -f
    experimental/users/ajaysundar/node-debugger/deploy/k8s-hack.yml`

Note: Use your valid gcr registry path as above.

## API Endpoints

The service listens on port `3100`.

*   Create a port-forwarding from the `node-collector` pod to your cloudtop.

    *   **Example:** `kubectl port-forward node-debugger-22d5t -n kube-system 3100:3100`

*   `GET /ping`: A simple health check endpoint that returns "ok".

    *   **Example:** `curl http://127.0.0.1:3100/ping`

*   `GET /history`: Returns a JSON array of the last 15 minutes of node vmstat
    data.

    *   **Example:** `curl http://127.0.0.1:3100/history`

*   `GET /stream`: Streams live node vmstat data using Server-Sent Events.

    *   **Example:** `curl -N -H "Accept: text/event-stream" http://127.0.0.1:3100/stream`
