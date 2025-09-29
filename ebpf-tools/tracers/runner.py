"""Runner for eBPF tracers.

This script loads a configuration file that specifies a list of eBPF tracers
to run, and then starts each tracer as a subprocess. It monitors the tracers
and can be reconfigured by updating the config file.
"""

import argparse
import os
import subprocess
import time
import yaml
import signal

CONFIG = "/etc/ebpf/config.yaml"


def load_config(config_path: str):
  """Loads the tracer configuration from a YAML file."""
  with open(config_path) as f:
    return yaml.safe_load(f)


def run_tracers(tracer_list: list[str]):
  """Starts a list of tracers as subprocesses.

  Args:
    tracer_list: A list of tracer script names to run.

  Returns:
    A list of Popen objects for the started processes.
  """
  procs = []
  for tracer in tracer_list:
    path = os.path.join("/tracers", tracer)
    if os.path.exists(path):
      print(f"Starting tracer: {tracer}")
      # Redirect stdout/stderr to capture output from tracers
      p = subprocess.Popen(
          ["python3", path],
          stdout=subprocess.PIPE,
          stderr=subprocess.PIPE,
          text=True,
      )
      procs.append(p)
    else:
      print(f"Tracer {tracer} not found")
  return procs


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="eBPF Tracer Runner")
  parser.add_argument(
      "--config",
      default=CONFIG,
      help=f"Path to the config file (default: {CONFIG})",
  )
  args = parser.parse_args()

  cfg = load_config(args.config)
  tracers = cfg if isinstance(cfg, list) else []
  procs = run_tracers(tracers)

  def shutdown(signum, frame):
    """Gracefully shut down all tracer subprocesses."""
    print(f"Received signal {signum}. Shutting down tracers...")
    for p in procs:
      # Tracers handle KeyboardInterrupt (SIGINT) for cleanup
      p.send_signal(signal.SIGINT)

    # Wait for all processes to terminate
    for p in procs:
      p.wait()

    print("All tracers have been shut down. Exiting.")
    exit(0)

  # Register signal handlers for graceful shutdown
  signal.signal(signal.SIGINT, shutdown)
  signal.signal(signal.SIGTERM, shutdown)

  print(
      "Runner started, tracers are running. Waiting for tracers to exit or"
      " signal to terminate."
  )

  # Monitor the tracer processes. If any of them exit, we shut down the rest.
  while True:
    for p in procs:
      if p.poll() is not None:
        # Read stdout/stderr to get the error message
        stdout, stderr = p.communicate()
        print(
            f"Tracer process {p.pid} exited unexpectedly with code"
            f" {p.returncode}. Shutting down."
        )
        if stdout:
          print(f"--- STDOUT ---\n{stdout.strip()}")
        if stderr:
          print(f"--- STDERR ---\n{stderr.strip()}")
        shutdown(None, None)
    time.sleep(5)
