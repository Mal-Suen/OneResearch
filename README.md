# OneResearch（一次调研）

把编码智能体做联网调研时的多轮「搜索→读→再搜」循环，折叠成 **1 次 MCP 工具调用**。工具内部自主完成双引擎搜索、并发抓取、正文提取、相关性排序与浓缩，返回一份可直接作答的调研报告。

## 为什么需要它

按请求次数计费的 coding plan 下，一次典型联网调研要消耗 15～30 次计费请求——每轮搜索、每页阅读之后，模型都要再处理一次。用 OneResearch：

- 调用 `research` 1 次（内部完成全部搜索与阅读）＋模型读报告作答 ≈ **1～2 次计费请求**
- 实测对照：同题调研 15～30 次请求 → 1～2 次；同题二跑命中 2 小时缓存后再省掉整个搜索阶段（实测 75s→44s，缓存省下的时间反哺 LLM 合成成功）
- 内部 LLM 通道零新 key：自动复用 Qwen Code 当前模型配置

## 工具

### research(question, depth, focus, recency, max_sources)

一次性联网调研。内部流水线：查询扩展（默认经内部 LLM 生成，可关）→ DuckDuckGo（走代理）＋百度（直连，首页 cookie 引导）双引擎搜索 → 域名过滤与权威度加权 → 并发抓取（单页超时＋体积上限＋整体 deadline）→ trafilatura 正文提取 → 段落级打分浓缩（关键词覆盖＋来源权威度＋时效＋内容指纹去重＋反爬挑战页过滤）→ 报告。

| 参数 | 说明 |
|---|---|
| question | 调研问题，中英文均可 |
| depth | quick（约 30 秒）／standard（默认，约 50 秒）／deep（更多查询与来源，约 80 秒） |
| focus | 可选，聚焦关键词，并入查询与排序权重 |
| recency | 可选，month／year，时效加权 |
| max_sources | 报告最多纳入的来源数，默认 8，上限 12 |

自动行为：standard／deep 时间允许时检测关键词缺口并自动补一轮定向搜索；对产品类问题自动追加「最新版本 release notes」保鲜查询（LLM 模式同样保留）；同题 2 小时内复用搜索结果缓存；超过约 18 个月的来源标注时效提醒。

报告包含：LLM 合成结论（带 [S#] 引用，可关）、各来源要点摘录（每源标注正文字数与摘录字数）、来源清单、未覆盖关键词缺口清单——缺口清单用于防止主模型读完报告后忍不住自己再搜一轮。

### fetch_digest(urls, question)

已知目标页面时批量抓取＋提取＋浓缩，一次调用读回最多 10 页，不要逐个 fetch。

## 安装

```shell
python -m pip install -r requirements.txt
# 国内网络可走镜像：
python -m pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
```

注册 Qwen Code：直接编辑 `~/.qwen/settings.json` 的 `mcpServers`（不要用 `qwen mcp add`——它会把整串命令塞进 command 字段，Windows 下启动失败）：

```json
"oneresearch": {
  "command": "<你的 Python 解释器路径>",
  "args": ["-u", "<项目根目录>/server.py"]
}
```

接入 DSH（DeepSeek Harness）：`dsh-bundle/` 目录是现成的配置型 bundle（dsh-mcp-client stdio 连接，工具调用超时放宽到 180 秒）。在该目录 `npm pack` 后把 tgz 路径交给 plugin_manager 的 install_bundle 即可（Windows 未开开发者模式时目录直装会因符号链接权限失败，tarball 走 file: 协议复制安装无此问题）。

改完重启 Qwen Code 生效；`qwen mcp list` 应显示 Connected。配合全局 `~/.qwen/QWEN.md` 的「联网调研工具规则」，新会话做调研会优先调用本工具。

## 配置

复制 `config.example.json` 为 `config.json`（已被 .gitignore 排除）：

- `proxy`：DuckDuckGo 依赖代理，默认 `http://127.0.0.1:7890`（常见本地代理端口，按你的代理工具修改），每次调研时探测，不在线自动只用百度（并直接跳过 DDG，不再白等超时）
- `llm`：默认零配置——自动读取 Qwen Code 的 settings.json，复用当前激活模型（端点＋密钥＋模型名）做内部查询生成与报告合成，不引入任何新 API key。想换更省的辅助模型只改 `model` 字段（端点密钥仍自动复用；合成建议用快而无思考的模型，必思考模型也能用——网关要求 thinking 时自动带上并追加思考预算，只是更慢）；设 `"enabled": false` 回到纯本地材料模式；也可显式填 base_url／api_key／model 指向任意 OpenAI 兼容服务（显式配置优先）
- `doubao`：豆包搜索 API key 插槽（预留，后续版本接入为第三搜索后端）
- 环境变量覆盖：`ONERESEARCH_PROXY`、`ONERESEARCH_LLM_BASE_URL`、`ONERESEARCH_LLM_API_KEY`、`ONERESEARCH_LLM_MODEL`

## 目录结构

```
OneResearch/
├── server.py              # MCP 服务器入口（注册路径指向这里）
├── oneresearch/
│   ├── pipeline.py        # 调研流水线编排（research / fetch_digest）
│   ├── queries.py         # 检索词抽取与本地查询扩展
│   ├── engines.py         # 双引擎搜索与结果页解析（DDG / 百度）
│   ├── cache.py           # 同题 2 小时参数级搜索缓存
│   ├── fetch.py           # 并发网页抓取（超时 / 体积 / deadline 三重预算）
│   ├── extract.py         # 正文提取（trafilatura 主，bs4 兜底）
│   ├── rank.py            # 相关性打分与浓缩（权威度 / 时效 / 指纹去重）
│   ├── report.py          # 报告组装（四种形态）
│   ├── llm.py             # 内部 LLM 通道（查询生成 / 报告合成 / thinking 自适应 / 两级重试）
│   └── config.py          # 配置加载与 Qwen Code 模型自动发现
├── dsh-bundle/            # DSH 接入 bundle（dsh-mcp-client stdio 配置）
├── tests/                 # 32 项单测 + 实网冒烟 + MCP stdio 冒烟 + LLM 通道诊断
├── docs/
│   ├── 设计取舍.md         # 引擎选型实测、降级链、结构性边界
│   └── 验证记录.md         # 全部验证轮次与实测数据
├── config.example.json
└── README.md
```

## 验证摘要

- 32 项离线单测全过；MCP stdio 握手约 0.7 秒；`qwen mcp list` Connected；DSH 侧经 dsh-bundle 接入后工具实调出报告
- 效果实测 4 组全通，合成报告与已知基准事实全部吻合（详见 `docs/验证记录.md`）
- 子会话实证：全新会话做调研的第一动作即调用 research，按报告缺口清单用 fetch_digest 定向补读

## 开发

```shell
python -m pytest tests -v
python tests/smoke_live.py
python tests/smoke_mcp.py
```

设计取舍与结构性边界见 `docs/设计取舍.md`。
