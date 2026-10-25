# -*- coding: utf-8 -*-
"""诊断脚本（手动运行）：验证 python -m oneresearch 入口的 MCP stdio 握手。python tests/diag_module_entry.py"""
import json
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass


def main() -> None:
    p = subprocess.Popen([sys.executable, "-u", "-m", "oneresearch"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, encoding="utf-8")

    def send(obj: dict) -> None:
        p.stdin.write(json.dumps(obj) + "\n")
        p.stdin.flush()

    t0 = time.time()
    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                     "clientInfo": {"name": "diag", "version": "0"}}})
    line = p.stdout.readline()
    msg = json.loads(line)
    assert "result" in msg, f"initialize 失败：{msg}"
    print(f"[1] python -m oneresearch initialize OK {(time.time() - t0) * 1000:.0f}ms "
          f"server={msg['result']['serverInfo']}")

    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    msg = json.loads(p.stdout.readline())
    names = [t["name"] for t in msg["result"]["tools"]]
    print(f"[2] tools/list OK：{names}")
    assert "research" in names and "fetch_digest" in names
    p.terminate()
    print("（-m 入口冒烟通过）")


if __name__ == "__main__":
    main()
