# -*- coding: utf-8 -*-
"""可选的内部 LLM 通道：OpenAI 兼容接口（查询生成＋报告合成）。未配置时流水线走纯本地模式。

两类网关兼容处理（2026-10-26 实测）：
- httpx 客户端一律 trust_env=False：本机 NO_PROXY 含 IPv6 字面量 [::1] 时，
  httpx 解析环境代理直接抛 InvalidURL（llm 通道全程静默失败即此根因）；
  代理由 OneResearch 自身探测后显式传入，不读环境变量，行为确定。
- 必思考模型（如 CTyun 网关的 glm-5.3）不带 thinking 参数会回 400
  「thinking must be enabled」：自动带 thinking 重试，且 max_tokens 需追加
  思考预算（该网关的 reasoning 与正文共享 max_tokens，不追加则正文被截空）。
"""
import asyncio
import json
import re

import httpx


class LLMError(Exception):
    pass


def _endpoint(base_url: str) -> str:
    b = base_url.rstrip("/")
    if b.endswith("/chat/completions"):
        return b
    return b + "/chat/completions"


def _needs_thinking(error_body: str) -> bool:
    """400 响应体是否表明该模型必须开启 thinking（如 CTyun 的 glm-5.3）。"""
    low = (error_body or "").lower()
    if "thinking" in low and "must be enabled" in low:
        return True
    return any(m in (error_body or "") for m in ("需要开启思考", "请开启思考",
                                                 "必须开启思考"))


_THINKING_TOKEN_BUDGET = 4000  # 思考模型的 reasoning 与正文共享 max_tokens


_SENSITIVE_TERMS = ("解密", "破解", "脱壳", "提取密钥", "密钥提取", "decrypt", "crack")


def _sanitize_material(material: str) -> str:
    """把易触发网关内容审核的安全类词汇替换为占位符（仅用于内部合成重试）。
    报告下方的原始摘录不受影响，主模型仍能看到完整材料。"""
    out = material
    for t in _SENSITIVE_TERMS:
        out = out.replace(t, "「已过滤」")
    return out


_RETRYABLE_STATUS = (429, 500, 502, 503, 504)


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 45.0):
        self.endpoint = _endpoint(base_url)
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._thinking = False  # 网关要求开启 thinking 后置 True，后续调用直接带上

    def _build_payload(self, system: str, user: str, temperature: float,
                       max_tokens: int) -> dict:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self._thinking:
            payload["thinking"] = {"type": "enabled"}
            payload["max_tokens"] = max_tokens + _THINKING_TOKEN_BUDGET
        return payload

    async def chat(self, system: str, user: str, temperature: float = 0.2,
                   max_tokens: int = 4000) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        for attempt in range(3):
            payload = self._build_payload(system, user, temperature, max_tokens)
            try:
                async with httpx.AsyncClient(timeout=self.timeout,
                                             trust_env=False) as client:
                    r = await client.post(self.endpoint, json=payload,
                                          headers=headers)
                if (r.status_code == 400 and not self._thinking
                        and _needs_thinking(r.text)):
                    self._thinking = True
                    continue  # 立即带 thinking 重试（不计退避）
                r.raise_for_status()
                data = r.json()
                try:
                    return data["choices"][0]["message"]["content"] or ""
                except Exception as e:
                    raise LLMError(f"LLM 响应解析失败：{e}") from e
            except httpx.HTTPStatusError as e:
                # 瞬时错误（限流/网关抖动）递增退避后重试（最多 2 次）
                if e.response.status_code in _RETRYABLE_STATUS and attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise
        raise LLMError("LLM 调用失败")

    async def gen_queries(self, question: str, n: int = 3) -> list[str]:
        system = ("你是搜索查询生成器。针对给定的调研问题，生成互补的搜索查询"
                  "（覆盖不同角度、同义词、中英文，至少一条面向官方文档或最新版本信息），"
                  "只输出 JSON 字符串数组，不要任何其他文字。")
        content = await self.chat(system, f"调研问题：{question}\n最多 {n} 条。",
                                  temperature=0.3, max_tokens=400)
        # 先尝试整体解析，再逐个尝试无嵌套的 [...] 段（LLM 可能带前置文字）
        for text in [content.strip(), *re.findall(r"\[[^\[\]]*\]", content)]:
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(parsed, list):
                continue
            queries = [q.strip() for q in parsed
                       if isinstance(q, str) and q.strip()]
            if queries:
                return queries[:n]
        raise LLMError("LLM 未返回 JSON 数组")

    async def synthesize(self, question: str, material: str) -> str:
        system = (
            "你是调研分析师。根据给定的多来源材料写一份中文调研报告："
            "先给 3～6 条关键结论（每条用来源编号标注，如 [S1]），再分主题小节展开；"
            "保留具体数字、版本号、日期；材料不足以判断的地方明确写「材料未覆盖」，不要编造。"
            "用 Markdown 输出，控制在 1500 字内。"
        )
        try:
            return await self.chat(
                system, f"调研问题：{question}\n\n材料：\n{material}",
                temperature=0.2, max_tokens=3000)
        except httpx.HTTPStatusError:
            # 网关内容审核对安全类词汇可能回 500：用过滤后的材料重试一次
            sanitized = _sanitize_material(material)
            if sanitized == material:
                raise
            return await self.chat(
                system, f"调研问题：{question}\n\n材料：\n{sanitized}",
                temperature=0.2, max_tokens=3000)
