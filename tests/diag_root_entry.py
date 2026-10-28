# -*- coding: utf-8 -*-
"""诊断脚本（手动运行）：验证已安装 bundle 的确切启动命令。python tests/diag_root_entry.py"""
import json
import subprocess
import sys
import threading
import time

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

CMD = [r"D:\ProgramData\anaconda3\python.exe", "-u",
       r"E:\PrometheusProjects\OneResearch\server.py"]


def main() -> None:
    p = subprocess.Popen(CMD, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8")

    def drain_err() -> None:
        err = p.stderr.read()
        if err.strip():
            print("STDERR:", err[:600])

    threading.Thread(target=drain_err, daemon=True).start()
    p.stdin.write(json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "diag", "version": "0"}}}) + "\n")
    p.stdin.flush()
    line = p.stdout.readline()
    if not line:
        print("NO RESPONSE — server died or hung")
        time.sleep(3)
        print("alive:", p.poll() is None, "| exit code:", p.returncode)
        return
    msg = json.loads(line)
    print("initialize OK:", msg.get("result", {}).get("serverInfo"))
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
    p.stdin.flush()
    line = p.stdout.readline()
    msg = json.loads(line)
    print("tools:", [t["name"] for t in msg["result"]["tools"]])
    p.terminate()


if __name__ == "__main__":
    main()
