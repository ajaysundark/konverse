#!/usr/bin/env python3
"""Traces Process Fork and Exit events and submits them to a collector.

This script uses eBPF to trace the `sched_process_fork` and `sched_process_exit`
kernel tracepoints.
When a new container is created, or an existing container is destroyed, this
script captures the process ID, command, and timestamp as an event,
and sends this information as a JSON payload to a configurable HTTP endpoint.
"""
import os
import time
from bcc import BPF
import requests

COLLECTOR = os.environ.get("COLLECTOR_URL", "http://127.0.0.1:3101/events")
CGROOT = os.environ.get("CGROOT", "/sys/fs/cgroup")
KUBE_SLICE = os.environ.get("K8S_SLICE", "kubepods.slice")
KUBE_SLICE_CGROUP = os.path.join(CGROOT, KUBE_SLICE)

# eBPF C program for process tracking
bpf_text = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h> // For task_struct

// The offset of the 'path' field from the start of the tracepoint data
#define PATH_OFFSET 24

// Structure to hold event data
struct data_t {
    u64 ts_ns;
    u32 type;  // 0: create, 1: exit
    u32 root;
    u32 level;
    u64 id;
    char path[256]; // Max path length for the cgroup
};

// Map to send data from kernel to userspace
BPF_PERF_OUTPUT(events);

// Tracepoint handler for cgroupfs dir creation
TRACEPOINT_PROBE(cgroup, cgroup_mkdir) {
    struct data_t data = {};
    data.ts_ns = bpf_ktime_get_ns();
    data.type = 0;
    data.root = args->root;
    data.level = args->level;
    data.id = args->id;
    TP_DATA_LOC_READ_STR(&data.path, path, sizeof(data.path));
    events.perf_submit(args, &data, sizeof(data));
    return 0;
}

// Tracepoint handler for cgroupfs dir deletion
TRACEPOINT_PROBE(cgroup, cgroup_rmdir) {
    struct data_t data = {};
    data.ts_ns = bpf_ktime_get_ns();
    data.type = 1;
    data.root = args->root;
    data.level = args->level;
    data.id = args->id;
    TP_DATA_LOC_READ_STR(&data.path, path, sizeof(data.path));
    events.perf_submit(args, &data, sizeof(data));
    return 0;
}
"""

# Initialize BPF and load the program
b = BPF(text=bpf_text)

# Calculate boot time to convert monotonic timestamps to wall-clock time
boot_time = time.time() - time.monotonic()


def submit(ev):
  """Formats and submits a process event to the collector."""
  cgid = ev.id
  cgpath = ev.path.decode(errors="ignore").strip("\x00")
  print(f"Event: {ev}", flush=True)
  if not cgpath.startswith(KUBE_SLICE_CGROUP):
    return
  reason = (
      f"root={ev.root} id={cgid} level={ev.level} path={cgpath} started"
      if ev.type == 0
      else f"root={ev.root} id={cgid} level={ev.level} path={cgpath} exited"
  )
  event_time = boot_time + (ev.ts_ns / 1e9)
  payload = {
      "ts": time.strftime(
          "%Y-%m-%dT%H:%M:%S%z", time.localtime(event_time)
      ),
      "type": "container_create" if ev.type == 0 else "container_delete",
      "cgroup_path": cgpath,
      "pid": cgid,
      "comm": "unknown",
      "reason": reason,
  }
  try:
    # requests.post(COLLECTOR, json=payload, timeout=0.5)
    print(f"POSTING: {payload}", flush=True)
  except Exception:
    print("ERR: failed to post to collector", flush=True)
    pass


# Function to handle incoming events
def on_event(cpu, data, size):
  event = b["events"].event(data)
  submit(event)


# Start polling for events
b["events"].open_perf_buffer(on_event)
print("ps_tracer posting events to ", COLLECTOR, flush=True)
while True:
  try:
    b.perf_buffer_poll()
  except KeyboardInterrupt:
    exit()
