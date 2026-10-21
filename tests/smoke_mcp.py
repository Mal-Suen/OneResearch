# -*- coding: utf-8 -*-
"""MCP stdio 冒烟（手动运行）：python tests/smoke_mcp.py
覆盖 initialize 握手 → tools/list → research 实调。"""
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass


def main() -> None:
    err_path = ROOT / "tests" / "smoke_mcp_stderr.log"
    err = open(err_path, "w", encoding="utf-8")
    p = subprocess.Popen([PY, "-u", str(ROOT / "server.py")],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=err, text=True, encoding="utf-8", cwd=str(ROOT))

    def send(obj: dict) -> None:
        p.stdin.write(json.dumps(obj) + "\n")
        p.stdin.flush()

    def recv(want_id, timeout: float):
        end = time.time() + timeout
        while time.time() < end:
            line = p.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == want_id:
                return msg
        return None

    t0 = time.time()
    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                     "clientInfo": {"name": "smoke", "version": "0"}}})
    init = recv(1, 30)
    assert init and "result" in init, f"initialize 失败：{init}"
    print(f"[1] initialize OK {(time.time() - t0) * 1000:.0f}ms "
          f"server={init['result']['serverInfo']}")

    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = recv(2, 20)
    names = [t["name"] for t in tools["result"]["tools"]]
    print(f"[2] tools/list OK：{names}")
    assert "research" in names and "fetch_digest" in names

    send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
          "params": {"name": "research",
                     "arguments": {"question": "pyJianYingDraft 最新版本与剪映兼容性",
                                   "depth": "quick"}}})
    res = recv(3, 150)
    assert res and "result" in res, f"research 调用失败：{res}"
    text = res["result"]["content"][0]["text"]
    print(f"[3] research OK，报告 {len(text)} 字，前 500 字：\n")
    print(text[:500])
    p.terminate()
    err.close()
    print("\n（MCP 冒烟通过）")


if __name__ == "__main__":
    main()
