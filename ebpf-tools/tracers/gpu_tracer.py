#!/usr/bin/python3
#
# gpuevent_hist.py   GPU event tracing for CUDA kernel launches, malloc, and memcpy.
#                    For Linux, uses BCC, eBPF.
#
# Run as root. Requires cuda libraries for probing user-space CUDA functions.
#
# Copyright (c) 2025 Your Name
# Licensed under the MIT License.
#
# Example usage:
#    sudo python3 gpuevent_hist.py

from __future__ import print_function
from time import sleep
from bcc import BPF

# Maximum number of kernel arguments to capture
MAX_GPUKERN_ARGS = 8

bpf_text = f"""
#include <uapi/linux/ptrace.h>

struct pid_info_t {{
    u32 pid;
    u32 tgid;
}};

struct gpu_kernel_launch_t {{
    u32 flags;
    struct pid_info_t pid_info;
    u64 kern_func_off;
    u32 grid_x, grid_y, grid_z;
    u32 block_x, block_y, block_z;
    u64 stream;
    u64 args[{MAX_GPUKERN_ARGS}];
}};

struct gpu_malloc_t {{
    u32 flags;
    struct pid_info_t pid_info;
    s64 size;
}};

struct gpu_memcpy_t {{
    u32 flags;
    struct pid_info_t pid_info;
    s64 size;
    u8 kind;
}};

BPF_HISTOGRAM(launch_grid_x);
BPF_HISTOGRAM(malloc_size_kb);
BPF_HISTOGRAM(memcpy_size_kb);

static int valid_pid(u64 id) {{
    // Only trace non-kernel (user) processes:
    return id >> 32 != 0;
}}

int trace_cudaLaunchKernel(struct pt_regs *ctx, u64 func_off, u64 grid_xy, u64 grid_z, u64 block_xy, u64 block_z, u64 argv) {{
    u64 id = bpf_get_current_pid_tgid();

    if (!valid_pid(id))
        return 0;

    struct gpu_kernel_launch_t e = {{}};
    e.flags = 1;
    e.pid_info.pid = id & 0xFFFFFFFF;
    e.pid_info.tgid = id >> 32;
    e.kern_func_off = func_off;
    e.grid_x = (u32)grid_xy;
    e.grid_y = (u32)(grid_xy >> 32);
    e.grid_z = (u32)grid_z;
    e.block_x = (u32)block_xy;
    e.block_y = (u32)(block_xy >> 32);
    e.block_z = (u32)block_z;

    // Histogram for grid_x
    launch_grid_x.increment(bpf_log2l(e.grid_x ? e.grid_x : 1));

    return 0;
}}

int trace_cudaMalloc(struct pt_regs *ctx, void **devPtr, size_t size) {{
    u64 id = bpf_get_current_pid_tgid();

    if (!valid_pid(id))
        return 0;

    struct gpu_malloc_t e = {{}};
    e.flags = 2;
    e.pid_info.pid = id & 0xFFFFFFFF;
    e.pid_info.tgid = id >> 32;
    e.size = (s64)size;

    // Histogram for malloc size in KB
    malloc_size_kb.increment(bpf_log2l(size / 1024 ? size / 1024 : 1));

    return 0;
}}

int trace_cudaMemcpyAsync(struct pt_regs *ctx, void *dst, void *src, size_t size, u8 kind) {{
    u64 id = bpf_get_current_pid_tgid();

    if (!valid_pid(id))
        return 0;

    struct gpu_memcpy_t e = {{}};
    e.flags = 3;
    e.pid_info.pid = id & 0xFFFFFFFF;
    e.pid_info.tgid = id >> 32;
    e.size = (s64)size;
    e.kind = kind;

    // Histogram for memcpy size in KB
    memcpy_size_kb.increment(bpf_log2l(size / 1024 ? size / 1024 : 1));

    return 0;
}}
"""

b = BPF(text=bpf_text)

# Attach uprobes to CUDA user-space functions (assumes libcudart.so is available)
import os


def find_cudart_so():
  # Try to find libcudart.so in LD_LIBRARY_PATH or common install locations
  from glob import glob

  paths = [
      "/usr/local/cuda/lib64/libcudart.so",
      "/usr/local/cuda/lib64/libcudart.so.10.2",
      "/usr/local/cuda/lib64/libcudart.so.11.0",
      "/usr/lib/x86_64-linux-gnu/libcudart.so",
      "/usr/lib/x86_64-linux-gnu/libcudart.so.10.2",
      "/usr/lib/x86_64-linux-gnu/libcudart.so.11.0",
  ]
  for p in paths:
    if os.path.isfile(p):
      return p
  # Try to find any libcudart.so
  found = glob("/usr/local/cuda*/lib64/libcudart.so*") + glob(
      "/usr/lib*/libcudart.so*"
  )
  for p in found:
    if os.path.isfile(p):
      return p
  return None


libcudart = find_cudart_so()
if not libcudart:
  print("ERROR: Could not find libcudart.so. Please specify its path.")
  exit(1)

# Attach uprobes
b.attach_uprobe(
    name=libcudart, sym="cudaLaunchKernel", fn_name="trace_cudaLaunchKernel"
)
b.attach_uprobe(name=libcudart, sym="cudaMalloc", fn_name="trace_cudaMalloc")
b.attach_uprobe(
    name=libcudart, sym="cudaMemcpyAsync", fn_name="trace_cudaMemcpyAsync"
)

print("Tracing CUDA kernel launches, malloc, and memcpy... Hit Ctrl-C to end.")

try:
  sleep(99999999)
except KeyboardInterrupt:
  print()

print("\nCUDA Kernel Launch grid_x histogram (log2 bins)")
print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
b["launch_grid_x"].print_log2_hist("grid_x dim")

print("\nCUDA Malloc size histogram (log2 bins, kbytes)")
print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
b["malloc_size_kb"].print_log2_hist("kbytes")

print("\nCUDA Memcpy size histogram (log2 bins, kbytes)")
print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
b["memcpy_size_kb"].print_log2_hist("kbytes")
