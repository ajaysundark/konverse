#!/bin/bash

set -e

# 1. Update package list and install the headers for the RUNNING kernel
echo "Installing kernel headers for $(uname -r)"
apt-get update
apt-get install -y linux-headers-$(uname -r)
echo "Kernel headers installed."

echo "Starting eBPF tracer runner..."
exec python3 /tracers/runner.py --config=/etc/ebpf/config.yaml