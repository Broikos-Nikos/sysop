"""LLM API client — Anthropic + OpenAI with SSE streaming via stdlib urllib."""
import json
import ssl
import sys
import time
import urllib.error
import urllib.request

# ANSI codes used to visually separate thinking from regular output.
_DIM = "\033[2m"
_RESET = "\033[0m"

# Minimum thinking budget (tokens).  4096 is enough for most sysadmin tasks.
_THINKING_BUDGET = 4096


class ToolCall:
    __slots__ = ("id", "name", "arguments")

    def __init__(self, id_, name, arguments):
        self.id = id_
        self.name = name
        self.arguments = arguments


class LLMResponse:
    __slots__ = ("text", "tool_calls", "stop_reason", "thinking_blocks")

    def __init__(self, text="", tool_calls=None, stop_reason="end_turn",
                 thinking_blocks=None):
        self.text = text
        self.tool_calls = tool_calls or []
        self.stop_reason = stop_reason
        # List of complete thinking block dicts {type, thinking, signature}.
        # Required by the Anthropic API when sending subsequent messages in the
        # same turn (tool-call continuity).
        self.thinking_blocks = thinking_blocks or []


_OPENAI_URLS = {
    "openai":   "https://api.openai.com/v1/chat/completions",
    "gemini":   "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "deepseek": "https://api.deepseek.com/v1/chat/completions",
}


class LLMClient:
    def __init__(self, config):
        self.provider = config["provider"]
        self.model = config["model"]
        self.api_key = config["api_key"]
        self.extended_thinking = (
            config.get("extended_thinking", False) and self.provider == "anthropic"
        )
        self._ctx = ssl.create_default_context()
        self._chat_url = _OPENAI_URLS.get(self.provider)

    def chat(self, messages, tools, system_prompt=""):
        """Send a chat request and return LLMResponse. Streams text to stdout."""
        if self.provider == "anthropic":
            return self._anthropic_chat(messages, tools, system_prompt)
        return self._openai_chat(messages, tools, system_prompt)

    # ── Anthropic ──────────────────────────────────────────────────────────────

    def _anthropic_chat(self, messages, tools, system_prompt):
        url = "https://api.anthropic.com/v1/messages"
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "stream": True,
            "messages": messages,
        }
        if system_prompt:
            body["system"] = system_prompt
        if tools:
            body["tools"] = tools
        if self.extended_thinking:
            body["thinking"] = {"type": "enabled", "budget_tokens": _THINKING_BUDGET}

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        if self.extended_thinking:
            # Interleaved thinking allows reasoning between tool calls.
            headers["anthropic-beta"] = "interleaved-thinking-2025-05-14"

        resp_text = ""
        tool_calls = []
        thinking_blocks = []
        stop_reason = "end_turn"

        # In-progress block trackers keyed by content block index.
        _current_tool = {}      # index -> {id, name, input_buf}
        _current_think = {}     # index -> {thinking_buf, signature_buf, printed}

        for event_type, data in self._sse_request(url, body, headers):
            if event_type == "content_block_start":
                block = data.get("content_block", {})
                idx = data.get("index", 0)
                btype = block.get("type", "")
                if btype == "tool_use":
                    _current_tool[idx] = {
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "input_buf": "",
                    }
                elif btype == "thinking":
                    _current_think[idx] = {
                        "thinking_buf": "",
                        "signature_buf": "",
                        "printed": False,
                    }

            elif event_type == "content_block_delta":
                delta = data.get("delta", {})
                idx = data.get("index", 0)
                dtype = delta.get("type", "")

                if dtype == "text_delta":
                    chunk = delta.get("text", "")
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
                    resp_text += chunk

                elif dtype == "thinking_delta":
                    chunk = delta.get("thinking", "")
                    if chunk and idx in _current_think:
                        tb = _current_think[idx]
                        if not tb["printed"]:
                            sys.stdout.write(_DIM + "\n")
                            tb["printed"] = True
                        # Indent each line of thinking output.
                        sys.stdout.write(chunk.replace("\n", "\n  "))
                        sys.stdout.flush()
                        tb["thinking_buf"] += chunk

                elif dtype == "signature_delta":
                    if idx in _current_think:
                        _current_think[idx]["signature_buf"] += delta.get("signature", "")

                elif dtype == "input_json_delta":
                    if idx in _current_tool:
                        _current_tool[idx]["input_buf"] += delta.get("partial_json", "")

            elif event_type == "content_block_stop":
                idx = data.get("index", 0)
                if idx in _current_tool:
                    tc = _current_tool.pop(idx)
                    try:
                        args = json.loads(tc["input_buf"]) if tc["input_buf"] else {}
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls.append(ToolCall(tc["id"], tc["name"], args))

                elif idx in _current_think:
                    tb = _current_think.pop(idx)
                    if tb["printed"]:
                        sys.stdout.write(_RESET + "\n")
                        sys.stdout.flush()
                    # Preserve the full thinking block (with signature) so it can be
                    # included in subsequent messages within the same turn.
                    thinking_blocks.append({
                        "type": "thinking",
                        "thinking": tb["thinking_buf"],
                        "signature": tb["signature_buf"],
                    })

            elif event_type == "message_delta":
                delta = data.get("delta", {})
                stop_reason = delta.get("stop_reason", stop_reason)

        if resp_text:
            print()  # Newline after streamed text.

        return LLMResponse(resp_text, tool_calls, stop_reason, thinking_blocks)

    # ── OpenAI ─────────────────────────────────────────────────────────────────

    def _openai_chat(self, messages, tools, system_prompt):
        url = self._chat_url

        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.extend(messages)

        body = {
            "model": self.model,
            "max_tokens": 4096,
            "stream": True,
            "messages": api_messages,
        }
        if tools:
            # Convert Anthropic-style tool defs to OpenAI format.
            body["tools"] = [
                {"type": "function", "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                }}
                for t in tools
            ]
            body["tool_choice"] = "auto"

        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer {}".format(self.api_key),
        }

        resp_text = ""
        # Accumulate tool call deltas: {index: {id, name, arguments_buf}}
        _tc_buf = {}
        stop_reason = "stop"

        for event_type, data in self._sse_request(url, body, headers, openai=True):
            choices = data.get("choices", [])
            if not choices:
                continue
            choice = choices[0]
            finish_reason = choice.get("finish_reason")
            if finish_reason:
                stop_reason = finish_reason

            delta = choice.get("delta", {})

            if "content" in delta and delta["content"]:
                chunk = delta["content"]
                sys.stdout.write(chunk)
                sys.stdout.flush()
                resp_text += chunk

            tcs = delta.get("tool_calls", [])
            for tc in tcs:
                idx = tc.get("index", 0)
                if idx not in _tc_buf:
                    _tc_buf[idx] = {"id": "", "name": "", "args_buf": ""}
                if tc.get("id"):
                    _tc_buf[idx]["id"] = tc["id"]
                fn = tc.get("function", {})
                if fn.get("name"):
                    _tc_buf[idx]["name"] = fn["name"]
                if fn.get("arguments"):
                    _tc_buf[idx]["args_buf"] += fn["arguments"]

        if resp_text:
            print()

        tool_calls = []
        for idx in sorted(_tc_buf.keys()):
            tc = _tc_buf[idx]
            try:
                args = json.loads(tc["args_buf"]) if tc["args_buf"] else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(tc["id"], tc["name"], args))

        return LLMResponse(resp_text, tool_calls, stop_reason)

    # ── SSE streaming core ─────────────────────────────────────────────────────

    def _sse_request(self, url, body, headers, openai=False, retries=1):
        """Yield (event_type, data_dict) pairs from an SSE response.

        Buffers bytes until double-newline, then parses each event block.
        """
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(body).encode(),
                    headers=headers,
                )
                with urllib.request.urlopen(req, context=self._ctx, timeout=120) as resp:
                    buf = b""
                    while True:
                        chunk = resp.read(512)
                        if not chunk:
                            break
                        buf += chunk
                        # Process all complete events (separated by \n\n).
                        while b"\n\n" in buf:
                            raw_event, buf = buf.split(b"\n\n", 1)
                            event_type, data = self._parse_sse_block(
                                raw_event.decode("utf-8", errors="replace"), openai
                            )
                            if data is not None:
                                yield event_type, data
                return
            except urllib.error.HTTPError as e:
                body_bytes = e.read()
                if e.code == 429:
                    retry_after = int(e.headers.get("retry-after", 10))
                    if attempt < retries:
                        print("\n  [rate limited — waiting {}s]".format(retry_after))
                        time.sleep(retry_after)
                        continue
                err_msg = ""
                try:
                    err_msg = json.loads(body_bytes).get("error", {}).get("message", "")
                except Exception:
                    err_msg = body_bytes.decode("utf-8", errors="replace")[:200]
                raise RuntimeError("API error {}: {}".format(e.code, err_msg)) from e
            except urllib.error.URLError as e:
                raise RuntimeError("Network error: {}".format(e.reason)) from e

    @staticmethod
    def _parse_sse_block(raw, openai=False):
        """Parse a single SSE event block into (event_type, data_dict).

        Returns (None, None) for heartbeats or [DONE] markers.
        """
        event_type = "message"
        data_str = None

        for line in raw.strip().split("\n"):
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_str = line[5:].strip()

        if data_str is None or data_str == "[DONE]":
            return None, None

        try:
            return event_type, json.loads(data_str)
        except json.JSONDecodeError:
            return None, None
