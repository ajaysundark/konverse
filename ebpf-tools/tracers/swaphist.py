#!/usr/bin/env python3
#
# swaphist.py - Trace page faults requiring swap and POST latency as JSON.
#
# This tool gathers swap fault latency data and sends it to a collector
# endpoint every 5 seconds for aggregation and analysis.

from datetime import datetime, timezone
import json
import os
import time
from bcc import BPF
import requests

# --- Configuration ---
# The collector URL can be set via an environment variable.
COLLECTOR_URL = os.getenv("COLLECTOR_URL", "http://127.0.0.1:3101/events")

# eBPF C program (this part is unchanged)
bpf_text = """
#include <uapi/linux/ptrace.h>

BPF_HASH(start, u32, u64);
BPF_HASH(swapped, u32, int);
BPF_HISTOGRAM(dist);

int trace_handle_mm_fault_start(struct pt_regs *ctx) {
    u32 tid = bpf_get_current_pid_tgid();
    u64 ts = bpf_ktime_get_ns();
    start.update(&tid, &ts);
    return 0;
}

int trace_do_swap_page_start(struct pt_regs *ctx) {
    u32 tid = bpf_get_current_pid_tgid();
    int flag = 1;
    swapped.update(&tid, &flag);
    return 0;
}

int trace_handle_mm_fault_end(struct pt_regs *ctx) {
    u64 *tsp, delta;
    u32 tid = bpf_get_current_pid_tgid();
    int *flagp;

    flagp = swapped.lookup(&tid);
    if (flagp == 0) {
        goto cleanup;
    }

    tsp = start.lookup(&tid);
    if (tsp == 0) {
        goto cleanup;
    }

    delta = bpf_ktime_get_ns() - *tsp;
    dist.increment(bpf_log2l(delta / 1000)); // ns to us

cleanup:
    start.delete(&tid);
    swapped.delete(&tid);
    return 0;
}
"""

# Initialize BPF
b = BPF(text=bpf_text)
b.attach_kprobe(event="handle_mm_fault", fn_name="trace_handle_mm_fault_start")
b.attach_kretprobe(event="handle_mm_fault", fn_name="trace_handle_mm_fault_end")
b.attach_kprobe(event="do_swap_page", fn_name="trace_do_swap_page_start")

print(f"Tracing swap fault latency and posting to {COLLECTOR_URL}...")
print("Hit Ctrl-C to end.")

# Main loop
try:
  while True:
    time.sleep(5)

    # Get the histogram data from the BPF map
    dist = b.get_table("dist")

    histogram_buckets = []
    for bucket, value in dist.items():
      if value.value == 0:
        continue
      # The bucket's 'slot' is the power-of-2 index
      # Calculate the human-readable range
      start_us = 2**bucket.value
      end_us = 2 ** (bucket.value + 1) - 1

      histogram_buckets.append({
          "range_start_us": start_us,
          "range_end_us": end_us,
          "count": value.value,
      })

    # Clear the BPF map for the next interval
    dist.clear()

    # Don't send empty events
    if not histogram_buckets:
      continue

    # Prepare the JSON payload
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": "swap_fault_latency",
        "latency_distribution_us": sorted(
            histogram_buckets, key=lambda x: x["range_start_us"]
        ),
    }

    # Send the data to the collector
    try:
      requests.post(COLLECTOR_URL, json=payload, timeout=5)
      print(
          f"[{payload['ts']}] Successfully posted event with"
          f" {len(payload['latency_distribution_us'])} buckets."
      )
    except requests.exceptions.RequestException as e:
      print(f"Error posting to collector: {e}")

except KeyboardInterrupt:
  print("\nDetaching...")
