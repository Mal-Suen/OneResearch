# -*- coding: utf-8 -*-
import asyncio
import json
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oneresearch.llm import (_THINKING_TOKEN_BUDGET, LLMClient, _endpoint,
                             _needs_thinking)


def _make_server() -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n))
            system = req["messages"][0]["content"]
            if "搜索查询生成器" in system:
                content = json.dumps(["查询一", "查询二"], ensure_ascii=False)
            else:
                content = "## 综合结论\n- 测试结论 [S1]"
            data = json.dumps({"choices": [{"message": {"role": "assistant",
                                                        "content": content}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_endpoint_join():
    assert _endpoint("https://api.deepseek.com") == "https://api.deepseek.com/chat/completions"
    assert _endpoint("https://api.deepseek.com/v1") == "https://api.deepseek.com/v1/chat/completions"
    assert _endpoint("https://x.com/v4/chat/completions") == "https://x.com/v4/chat/completions"


def test_llm_client_roundtrip():
    srv = _make_server()
    port = srv.server_address[1]

    async def main():
        client = LLMClient(f"http://127.0.0.1:{port}/v1", "sk-test", "test-model")
        queries = await client.gen_queries("测试问题", 3)
        assert queries == ["查询一", "查询二"]
        report = await client.synthesize("测试问题", "材料")
        assert "[S1]" in report

    asyncio.run(main())
    srv.shutdown()


def _make_sensitive_server() -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n))
            user = req["messages"][-1]["content"]
            if "解密" in user:
                data = b"Internal Server Error"
                self.send_response(500)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            content = "## 综合结论\n- 测试结论 [S1]"
            data = json.dumps({"choices": [{"message": {"role": "assistant",
                                                        "content": content}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_synthesize_sensitive_retry():
    srv = _make_sensitive_server()
    port = srv.server_address[1]

    async def main():
        client = LLMClient(f"http://127.0.0.1:{port}/v1", "sk-test", "test-model")
        report = await client.synthesize("测试", "材料提到解密实现，应触发过滤重试")
        assert "[S1]" in report

    asyncio.run(main())
    srv.shutdown()


def _make_flaky_server():
    state = {"count": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            self.rfile.read(n)
            state["count"] += 1
            if state["count"] == 1:
                data = b"Internal Server Error"
                self.send_response(500)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            content = "重试成功"
            data = json.dumps({"choices": [{"message": {"role": "assistant",
                                                        "content": content}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, state


def test_chat_transient_retry():
    """瞬时 5xx：退避后重试一次应成功（网关间歇抽风的通用兜底）。"""
    srv, state = _make_flaky_server()
    port = srv.server_address[1]

    async def main():
        client = LLMClient(f"http://127.0.0.1:{port}/v1", "sk-test", "test-model")
        content = await client.chat("sys", "user")
        assert "重试成功" in content
        assert state["count"] == 2

    asyncio.run(main())
    srv.shutdown()


def _make_prefix_server() -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n))
            system = req["messages"][0]["content"]
            if "搜索查询生成器" in system:
                content = '参考 [S1] 的思路，查询：["查询甲", "查询乙"]'
            else:
                content = "## 综合结论\n- 测试结论 [S1]"
            data = json.dumps({"choices": [{"message": {"role": "assistant",
                                                        "content": content}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_gen_queries_with_prefix_text():
    """LLM 返回带前置文字与多个方括号段时仍能提取查询数组（非贪婪解析）。"""
    srv = _make_prefix_server()
    port = srv.server_address[1]

    async def main():
        client = LLMClient(f"http://127.0.0.1:{port}/v1", "sk-test", "test-model")
        queries = await client.gen_queries("测试问题", 3)
        assert queries == ["查询甲", "查询乙"]

    asyncio.run(main())
    srv.shutdown()


def test_needs_thinking_detection():
    assert _needs_thinking('{"error":{"message":"thinking must be enabled for glm-5.3"}}')
    assert _needs_thinking("该模型需要开启思考模式")
    assert not _needs_thinking('{"error":{"message":"invalid api key"}}')
    assert not _needs_thinking("")


def _make_thinking_server() -> ThreadingHTTPServer:
    state = {"requests": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n))
            state["requests"].append(req)
            if "thinking" not in req:
                data = json.dumps({"error": {
                    "message": "thinking must be enabled for glm-5.3. (request id: x)",
                    "code": 400, "type": "upstream_error"}}).encode()
                self.send_response(400)
            else:
                content = "## 综合结论\n- 测试结论 [S1]"
                data = json.dumps({"choices": [
                    {"message": {"role": "assistant", "content": content}}]}).encode()
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, state


def test_chat_thinking_auto_retry():
    """网关要求 thinking 的模型：首次 400 后自动带 thinking 重试并追加思考预算，
    客户端记住状态，后续调用直接带 thinking。"""
    srv, state = _make_thinking_server()
    port = srv.server_address[1]

    async def main():
        client = LLMClient(f"http://127.0.0.1:{port}/v1", "sk-test", "glm-test")
        content = await client.chat("sys", "user", max_tokens=400)
        assert "[S1]" in content
        assert "thinking" not in state["requests"][0]
        second = state["requests"][1]
        assert second.get("thinking") == {"type": "enabled"}
        assert second["max_tokens"] == 400 + _THINKING_TOKEN_BUDGET
        await client.chat("sys", "user2", max_tokens=400)
        assert state["requests"][2].get("thinking") == {"type": "enabled"}
        assert len(state["requests"]) == 3  # 状态记住后不再触发 400

    asyncio.run(main())
    srv.shutdown()
