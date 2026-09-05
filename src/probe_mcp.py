#!/usr/bin/env python3
"""Smoke stdio MCP without opening the browser."""
import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
proc = subprocess.Popen(
    [str(root / ".venv/bin/python"), str(root / "src/mcp_server.py")],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)
msgs = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
]
raw = "".join(json.dumps(m) + "\n" for m in msgs)
out, err = proc.communicate(raw, timeout=20)
print("STDERR:", err[:500])
print("STDOUT:")
print(out)
sys.exit(0 if '"marriott_status"' in out else 1)
