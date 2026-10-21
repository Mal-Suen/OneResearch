# -*- coding: utf-8 -*-
"""实网冒烟（手动运行）：python tests/smoke_live.py
验证真实网络下的搜索→抓取→提取→报告全链路。"""
import asyncio
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

from oneresearch.pipeline import run_research


async def main() -> None:
    t0 = time.monotonic()
    report = await run_research("pyJianYingDraft 最新版本与剪映兼容性", depth="standard")
    print(report)
    print(f"\n（耗时 {time.monotonic() - t0:.0f}s，报告 {len(report)} 字）")


if __name__ == "__main__":
    asyncio.run(main())
