# OneResearch（一次调研）

把编码智能体做联网调研时的多轮「搜索→读→再搜」循环，折叠成 **1 次 MCP 工具调用**。工具内部自主完成双引擎搜索、并发抓取、正文提取、相关性排序与浓缩，返回一份可直接作答的调研报告。

## 为什么需要它

按请求次数计费的 coding plan 下，一次典型联网调研要消耗 15～30 次计费请求——每轮搜索、每页阅读之后，模型都要再处理一次。用 OneResearch：

- 调用 `research` 1 次（内部完成全部搜索与阅读）＋模型读报告作答 ≈ **1～2 次计费请求**
- 降幅约 90%；纯本地模式零额外 API 成本

## 工具

### research(question, depth, focus, recency, max_sources)

一次性联网调研。内部流水线：本地查询扩展 → DuckDuckGo（走代理）＋百度（直连，首页 cookie 引导）双引擎搜索 → 域名过滤与权威度加权 → 并发抓取（单页超时＋体积上限＋整体 deadline）→ trafilatura 正文提取 → 段落级打分浓缩（关键词覆盖＋来源权威度＋时效＋内容指纹去重＋反爬挑战页过滤）→ 报告。

| 参数 | 说明 |
|---|---|
| question | 调研问题，中英文均可 |
| depth | quick（约 30 秒）／standard（默认，约 50 秒）／deep（更多查询与来源，约 80 秒） |
| focus | 可选，聚焦关键词，并入查询与排序权重 |
| recency | 可选，month／year，时效加权 |
| max_sources | 报告最多纳入的来源数，默认 8，上限 12 |

报告包含：各来源要点摘录（每源标注正文字数与摘录字数）、来源清单、未覆盖关键词缺口。缺口清单用于防止主模型读完报告后忍不住自己再搜一轮。

### fetch_digest(urls, question)

已知目标页面时批量抓取＋提取＋浓缩，一次调用读回最多 10 页，不要逐个 fetch。

## 安装

```shell
D:\ProgramData\anaconda3\python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
```

注册 Qwen Code：直接编辑 `C:\Users\malco\.qwen\settings.json` 的 `mcpServers`（不要用 `qwen mcp add`——它会把整串命令塞进 command 字段，Windows 下启动失败）：

```json
"oneresearch": {
  "command": "D:\\ProgramData\\anaconda3\\python.exe",
  "args": ["-u", "E:\\PrometheusProjects\\OneResearch\\server.py"]
}
```

改完重启 Qwen Code 生效；`qwen mcp list` 应显示 Connected。

## 配置

复制 `config.example.json` 为 `config.json`（已被 .gitignore 排除）：

- `proxy`：DuckDuckGo 依赖代理，默认 Clash `http://127.0.0.1:7890`，每次调研时探测，不在线自动只用百度；百度直连不需要代理
- `llm`：填入 OpenAI 兼容的 `base_url`／`api_key`／`model` 后，查询生成与报告合成升级为内部 LLM 完成（DeepSeek、GLM、ARK 均可；base_url 填到 /v1 或等价前缀即可，自动拼接 /chat/completions）；不填走纯本地模式
- `doubao`：豆包搜索 API key 插槽（预留，后续版本接入为第三搜索后端）
- 环境变量覆盖：`ONERESEARCH_PROXY`、`ONERESEARCH_LLM_BASE_URL`、`ONERESEARCH_LLM_API_KEY`、`ONERESEARCH_LLM_MODEL`

## 验证记录（2026-10-22）

- 离线单测：13 passed（查询扩展、打分浓缩、指纹去重、挑战页过滤、DDG＋百度解析器、LLM mock 回环）
- 实网冒烟：「pyJianYingDraft 最新版本与剪映兼容性」standard 深度 6 秒完成，DDG 8 条＋百度 8 条，8 来源成报；报告挖到 0.3.1 已上 PyPI（2026-10-14）等可核对事实
- MCP stdio：initialize 767ms，tools/list 暴露 research＋fetch_digest，research 实调出报告
- `qwen mcp list`：oneresearch Connected

## 设计取舍

- **搜索引擎**：Bing 实测弃用——cn.bing.com 把 /search 重定向到 www.bing.com 首页，www.bing.com 对无浏览器指纹的自动化请求返回与查询无关的缓存结果；搜狗、360 直连进反爬验证页；百度需先访问首页拿 cookie 再搜索，实测稳定
- **纯本地 vs 内部 LLM**：纯本地模式的报告是「材料组织」而非「结论合成」——主模型一次读完材料自己下结论；配置 llm 后升级为带 [S#] 引用的合成报告，材料摘录仍附后供核对
- **deep 深度约 80 秒**：若客户端工具超时先于完成，调大 MCP_TOOL_TIMEOUT
- **DDG 依赖代理在线**：代理不在线时自动降级为仅百度，报告的引擎状态行会注明

## 开发

```shell
D:\ProgramData\anaconda3\python.exe -m pytest E:\PrometheusProjects\OneResearch\tests -v
D:\ProgramData\anaconda3\python.exe E:\PrometheusProjects\OneResearch\tests\smoke_live.py
D:\ProgramData\anaconda3\python.exe E:\PrometheusProjects\OneResearch\tests\smoke_mcp.py
```
