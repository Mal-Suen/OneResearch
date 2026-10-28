# 上游提案二：profile 热重载 bug 报告（草稿，待审核）

- 目标仓库：deepseek-ai/deepseek-harness
- 提交方式：待你审核通过后经 gh 提交（或你手动贴）

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

## 中文对照

标题：plugin_manager 写操作成功，但 profile 热重载始终报「profile reload requires the root Include entry」

正文要点：环境（dsh 0.2.1-rc.2、npm 全局安装、Windows 11、web profile）；复现步骤（任意写操作→pnpm 成功→application: failed 报同一诊断→重启才生效）；期望与实际；根因指针（dsh-app-boot 的 recompose() 里 bootstrapIncludes.get(ctx) 返回 undefined，疑似 web-profile 启动路径没注册根 Include 条目）；两个同机观察（失败操作残留 package.json.lock 死锁 14 小时才手动清除；受影响会话的 runtime context 把 implementation checkout 报成 profile 目录）；结尾表示可提供日志或协助验证修复。
