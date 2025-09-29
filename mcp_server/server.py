import json
import subprocess
from fastmcp import FastMCP
import requests

# Define the MCP server
mcp = FastMCP(name="GKE Node Diagnostics Server")


@mcp.tool
def memory_trend() -> dict:
  """Gathers memory and swap relevant debugging information for LLM Agent to analyze
  memory and swap influence on workload performance on this node.
  """
  results = {}

  # --- Helper function for running shell commands ---
  # def run_command(command, shell=False):
  #   try:
  #     # Using a list of args is safer unless a shell is required (for pipes)
  #     args = command if not shell else [command]
  #     result = subprocess.run(
  #         *args, capture_output=True, text=True, check=True, shell=shell
  #     )
  #     return result.stdout
  #   except FileNotFoundError:
  #     return f"Command not found: {command.split()[0]}"
  #   except subprocess.CalledProcessError as e:
  #     return f"Error running '{command}': {e.stderr}"
  #   except Exception as e:
  #     return f"An unexpected error occurred with '{command}': {e}"

  # --- Helper function for reading proc files ---
  # def read_proc_file(path):
  #   try:
  #     with open(path, "r") as f:
  #       return f.read()
  #   except FileNotFoundError:
  #     return f"File not found: {path}"
  #   except Exception as e:
  #     return f"Error reading {path}: {e}"

  # 1. Get current swap configuration from /proc/swaps
  # results["proc_swaps"] = read_proc_file("/proc/swaps")

  # 2. Get current free memory distribution
  # results["free_memory"] = run_command(["free", "-m"])

  # 3. Get PSI memory pressure
  # results["psi_memory"] = read_proc_file("/proc/pressure/memory")

  # 4. Get key memory info details
  # results["meminfo"] = run_command(
  #     "cat /proc/meminfo | grep -E 'Swap|MemAvailable|MemFree'", shell=True
  # )

  # 5. Get detailed kernel zone info
  # results["zoneinfo"] = read_proc_file("/proc/zoneinfo")

  # 6. Retrieve vmstat history from local collector
  try:
    response = requests.get(
        "http://127.0.0.1:3100/history?scope=stats", timeout=5
    )
    response.raise_for_status()
    results["vmstat_history"] = response.json()
  except requests.exceptions.RequestException as e:
    results["vmstat_history"] = f"Error fetching vmstat history: {e}"

  # 7. Retrieve eBPF events from local collector
  try:
    response = requests.get(
        "http://127.0.0.1:3100/history?scope=events", timeout=5
    )
    response.raise_for_status()
    results["ebpf_events"] = response.json()
  except requests.exceptions.RequestException as e:
    results["ebpf_events"] = f"Error fetching eBPF events: {e}"

  return results


if __name__ == "__main__":
  # Run the server as an HTTP service on port 8000, accessible from any IP
  mcp.run(transport="http", host="0.0.0.0", port=8000)
