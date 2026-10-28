# 上游提案二：profile 热重载 bug 报告（已发布）

- 目标仓库：deepseek-ai/deepseek-harness
- 发布渠道：GitHub Discussions（仓库关闭了 issues）→「General」分类（无专门 bug 分类，README 指明 bug 报告走 Discussions）
- 发布链接：https://github.com/deepseek-ai/deepseek-harness/discussions/11321
- 发布账号：Mal-Suen（gh CLI 认证账号，2026-10-28 经用户批准后发布）

## English draft

**Title:** plugin_manager writes succeed, but profile reload always fails with "profile reload requires the root Include entry"

**Body:**

**Environment**

- dsh 0.2.1-rc.2, npm global install, Windows 11, web profile (`dsh web` behind a reverse proxy, if that matters)
- Reproduced in two different sessions (one healthy, one degraded) on the same host

**Steps to reproduce**

1. Call the `plugin_manager` tool with any write action, e.g. `install_bundle` with a local tarball, or `set_plugin`/`set_bundle` enable/disable.
2. The pnpm step succeeds (package.json and node_modules update correctly).
3. The operation result is `application: "failed"` with:

```
dsh: profile reload requires the root Include entry
```

4. The change only takes effect after a full DSH restart.

**Expected:** live profiles apply plugin changes immediately (per the plugin_manager contract).

**Actual:** every write operation reports the same diagnostic; nothing applies until restart.

**Root-cause pointer**

The diagnostic comes from `recompose()` in `@deepseek-ai/dsh-app-boot` (lib/index.js, the `bootstrapIncludes.get(ctx)` check returning `undefined`). It looks like the root Include entry is not registered in `bootstrapIncludes` for this launch mode, so the reload path always throws. I have not determined why the entry is missing — possibly specific to the web-profile launch path.

**Two related observations from the same host**

1. A failed operation leaves `package.json.lock` behind. In our case a stale lock (containing a long-dead PID) blocked subsequent installs for ~14 hours until removed manually. The lock file was not cleaned up when the operation failed.
2. In the affected sessions, the runtime context reported the implementation checkout as the profile directory itself rather than the npm installation directory — possibly the same launch-mode quirk, reported here in case it is related.

Happy to provide logs or test a fix. Thanks!

## 中文对照（全文翻译）

**标题：** plugin_manager 写操作成功，但 profile 热重载始终报「profile reload requires the root Include entry」

**正文：**

**环境**

- dsh 0.2.1-rc.2，npm 全局安装，Windows 11，web profile（`dsh web` 经反向代理发布，如相关）
- 同一主机上两个不同会话复现（一个健康、一个降级）

**复现步骤**

1. 调用 `plugin_manager` 工具执行任意写操作，如对本地 tarball `install_bundle`，或 `set_plugin`／`set_bundle` 启停。
2. pnpm 步骤成功（package.json 与 node_modules 正确更新）。
3. 操作结果为 `application: "failed"`，诊断信息为：

```
dsh: profile reload requires the root Include entry
```

4. 改动只有完整重启 DSH 后才生效。

**期望：** live profile 立即应用插件改动（按 plugin_manager 契约）。

**实际：** 每个写操作都报同一诊断；重启前什么都不生效。

**根因指针**

该诊断出自 `@deepseek-ai/dsh-app-boot` 的 `recompose()`（lib/index.js，`bootstrapIncludes.get(ctx)` 检查返回 undefined）。看起来这个启动模式下根 Include 条目没有注册进 `bootstrapIncludes`，导致重载路径必然抛错。我尚未确定条目缺失的原因——可能与 web-profile 启动路径相关。

**同一主机的两个相关观察**

1. 失败操作会残留 `package.json.lock`。我们的案例里，一个含早已死亡 PID 的死锁阻塞了后续安装约 14 小时，直到手动删除。操作失败时锁文件没有被清理。
2. 受影响会话中，runtime context 把 implementation checkout 报成 profile 目录本身而非 npm 安装目录——可能是同一启动模式的怪癖，一并报告以防相关。

乐意提供日志或协助验证修复。谢谢！
