# -*- coding: utf-8 -*-
"""诊断脚本（手动运行）：验证启动自检 stderr 行。python tests/diag_boot_line.py"""
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

p = subprocess.Popen([sys.executable, "-u", "-m", "oneresearch"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.PIPE, text=True, encoding="utf-8")
time.sleep(3)
p.terminate()
err = p.stderr.read()
print("STDERR:", err.strip() or "(empty)")
assert err.strip().startswith("[oneresearch]"), "boot line missing"
print("（启动自检行验证通过）")
