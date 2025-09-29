#!/usr/bin/env python3
"""Traces OOM kill events and submits them to a collector.

This script uses eBPF to trace the `oom_kill_process` kernel tracepoint.
When an OOM kill occurs, it captures the process ID, command, and timestamp,
and sends this information as a JSON payload to a configurable HTTP endpoint.
"""
import os
import time
from bcc import BPF
import requests

COLLECTOR = os.environ.get("COLLECTOR_URL", "http://127.0.0.1:3101/events")
CGROOT = os.environ.get("CGROOT", "/sys/fs/cgroup")

bpf_text = r"""
#include <uapi/linux/ptrace.h>
#include <linux/oom.h>
#include <linux/sched.h>
#include <linux/nsproxy.h>
#include <linux/utsname.h>

struct data_t {
    u64 ts_ns;
    u32 fpid;
    char fcomm[16];
    u32 tpid;
    char tcomm[16];
    char nsproxy[16];
};

BPF_PERF_OUTPUT(events);

void kprobe__oom_kill_process(struct pt_regs *ctx, struct oom_control *oc, const char *message)
{
    struct data_t data = {};
    data.ts_ns = bpf_ktime_get_ns();
    // host pid (trigger)
    data.fpid = bpf_get_current_pid_tgid() >> 32;
    bpf_get_current_comm(&data.fcomm, sizeof(data.fcomm));
    // target pid (victim)
    data.tpid = oc->chosen->pid;
    bpf_probe_read_kernel(&data.tcomm, sizeof(data.tcomm), oc->chosen->comm);
    // container id
    bpf_probe_read_kernel(&data.nsproxy, sizeof(data.nsproxy), oc->chosen->nsproxy->uts_ns->name.nodename);

    events.perf_submit(ctx, &data, sizeof(data));
}
"""


"""Initializes BPF, attaches probes, and enters the polling loop."""
b = BPF(text=bpf_text)
# Calculate boot time to convert monotonic timestamps to wall-clock time
boot_time = time.time() - time.monotonic()


b.attach_kprobe(event="oom_kill_process", fn_name="kprobe__oom_kill_process")


def pid_to_cgpath(pid: int) -> str:
  """Resolves the cgroup path for a given process ID."""
  # Use /proc/<pid>/cgroup for v2 mapping
  try:
    with open(f"/proc/{pid}/cgroup", "r") as f:
      for line in f:
        parts = line.strip().split(":")
        if len(parts) == 3:
          path = parts[2]
          if path.startswith("/"):
            return os.path.join(CGROOT, path.lstrip("/"))
          return os.path.join(CGROOT, path)
  except FileNotFoundError:
    print("ERR: failed to find cgroup path for pid", pid, flush=True)
    pass
  return ""


def submit(ev):
  """Formats and submits an OOM event to the collector."""
  cgpath = pid_to_cgpath(ev.tpid)  # victim container cgroup path
  reason = "[%s] oom_kill_process: killed by %d (%s)" % (
      ev.nsproxy.decode(errors="ignore").strip("\x00"),
      ev.fpid,
      ev.fcomm.decode(errors="ignore").strip("\x00"),
  )
  print(f"OOM event: {reason}")
  event_time = boot_time + (ev.ts_ns / 1e9)
  payload = {
      "ts": time.strftime(
          "%Y-%m-%dT%H:%M:%S%z", time.localtime(event_time)
      ),
      "type": "oom",
      "container_id": ev.nsproxy.decode(errors="ignore").strip("\x00"),
      "cgroup_path": cgpath,
      "victim_pid": int(ev.tpid),
      "victim_comm": ev.tcomm.decode(errors="ignore").strip("\x00"),
      "trigger_pid": int(ev.fpid),
      "trigger_comm": ev.fcomm.decode(errors="ignore").strip("\x00"),
  }
  try:
    requests.post(COLLECTOR, json=payload, timeout=5)
  except Exception:
    print("ERR: failed to post to collector", flush=True)
    pass


def on_event(cpu, data, size):
  """Callback function for handling events from the eBPF perf buffer."""
  ev = b["events"].event(data)
  print(f"OOM event: {ev}")
  submit(ev)


b["events"].open_perf_buffer(on_event, page_cnt=64)
print("oom_tracer posting events to ", COLLECTOR, flush=True)
while True:
  try:
    b.perf_buffer_poll()
  except KeyboardInterrupt:
    exit()
