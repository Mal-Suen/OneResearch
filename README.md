# OneResearch（一次调研）

把编码智能体做联网调研时的多轮「搜索→读→再搜」循环，折叠成 **1 次 MCP 工具调用**。工具内部自主完成双引擎搜索、并发抓取、正文提取、相关性排序与浓缩，返回一份可直接作答的调研报告。

## 为什么需要它

按请求次数计费的 coding plan 下，一次典型联网调研要消耗 15～30 次计费请求——每轮搜索、每页阅读之后，模型都要再处理一次。用 OneResearch：

- 调用 `research` 1 次（内部完成全部搜索与阅读）＋模型读报告作答 ≈ **1～2 次计费请求**
- 降幅约 90%；纯本地模式零额外 API 成本

## 工具

### research(question, depth, focus, recency, max_sources)

一次性联网调研。内部流水线：查询扩展（默认经内部 LLM 生成，可关）→ DuckDuckGo（走代理）＋百度（直连，首页 cookie 引导）双引擎搜索 → 域名过滤与权威度加权 → 并发抓取（单页超时＋体积上限＋整体 deadline）→ trafilatura 正文提取 → 段落级打分浓缩（关键词覆盖＋来源权威度＋时效＋内容指纹去重＋反爬挑战页过滤）→ 报告。standard/deep 时间允许时检测关键词缺口自动补一轮定向搜索；对产品类问题自动追加「最新版本 release notes」保鲜查询（LLM 模式同样保留）；同题 2 小时内复用搜索结果缓存（含 LLM 模式）；超过约 18 个月的来源标注时效提醒。

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
- `llm`：默认零配置——自动读取 Qwen Code 的 settings.json，复用当前激活模型（端点＋密钥＋模型名）做内部查询生成与报告合成，不引入任何新 API key。想换更省的辅助模型（如 deepseek-v4-flash-0731-oc）只改 `model` 字段，端点密钥仍自动复用；设 `"enabled": false` 回到纯本地材料模式；也可显式填 base_url/api_key/model 指向任意 OpenAI 兼容服务（显式配置优先）。内部 LLM 调用直接打到该模型端点，按端点自身计费规则计
- `doubao`：豆包搜索 API key 插槽（预留，后续版本接入为第三搜索后端）
- 环境变量覆盖：`ONERESEARCH_PROXY`、`ONERESEARCH_LLM_BASE_URL`、`ONERESEARCH_LLM_API_KEY`、`ONERESEARCH_LLM_MODEL`

## 验证记录（2026-10-22）

- 离线单测：13 passed（查询扩展、打分浓缩、指纹去重、挑战页过滤、DDG＋百度解析器、LLM mock 回环）
- 实网冒烟：「pyJianYingDraft 最新版本与剪映兼容性」standard 深度 6 秒完成，DDG 8 条＋百度 8 条，8 来源成报；报告挖到 0.3.1 已上 PyPI（2026-10-14）等可核对事实
- MCP stdio：initialize 767ms，tools/list 暴露 research＋fetch_digest，research 实调出报告
- `qwen mcp list`：oneresearch Connected
- 2026-10-22 二次迭代：LLM 通道零配置自动发现（复用 Qwen Code 当前模型）实网验证；缺口驱动二轮／版本保鲜查询／2 小时搜索缓存／旧来源时效标注落地
- 2026-10-22 效果实测（4 组全通）：mcp/FastMCP 合成报告与已知事实全部吻合；pyCapCut 报告命中全部基准且 deep 缺口二轮实际触发；本地模式缓存命中 5s→2s。实测限流规律：DDG html 202 限流→lite 端点兜底；百度连发触发反爬→查询加 0.8s 间隔；双引擎轮流扛住
- 2026-10-23 迭代 3：LLM 瞬时错误（429/5xx）退避重试；缓存上移至调研参数级（question/depth/focus/recency 为键——LLM 模式同题二跑实测命中，跳过查询生成与搜索）；保鲜查询并入 LLM 查询（上限 5 条）；缺口二轮扩展至 standard

## 设计取舍

- **搜索引擎**：Bing 实测弃用——cn.bing.com 把 /search 重定向到 www.bing.com 首页，www.bing.com 对无浏览器指纹的自动化请求返回与查询无关的缓存结果；搜狗、360 直连进反爬验证页；百度需先访问首页拿 cookie 再搜索，实测稳定
- **内部 LLM 默认开启**：自动复用 Qwen Code 当前模型配置（零新 key），报告升级为带 [S#] 引用的合成结论，材料摘录仍附后供核对；设 `llm.enabled=false` 回到纯本地「材料组织」模式——主模型一次读完材料自己下结论
- **deep 深度约 80 秒**：若客户端工具超时先于完成，调大 MCP_TOOL_TIMEOUT
- **DDG 依赖代理在线**：代理不在线时自动降级为仅百度；html 端点限流（202）时自动退 lite 端点；引擎状态行如实标注结果数与疑似限流

## 开发

```shell
D:\ProgramData\anaconda3\python.exe -m pytest E:\PrometheusProjects\OneResearch\tests -v
D:\ProgramData\anaconda3\python.exe E:\PrometheusProjects\OneResearch\tests\smoke_live.py
D:\ProgramData\anaconda3\python.exe E:\PrometheusProjects\OneResearch\tests\smoke_mcp.py
```
