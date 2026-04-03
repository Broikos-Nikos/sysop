"""Conversation history with a sliding window of max N turns.

Messages are stored directly in Anthropic wire format (the richer format).
OpenAI format is derived on demand.  A "turn" is one user-initiated message
plus the full exchange (tool calls, results, final assistant text) that follows
it.  Trimming removes complete turns from the front so we never split a
tool-call/tool-result pair.

Anthropic message structure recap
──────────────────────────────────
user text     : {"role": "user", "content": "string"}
asst text     : {"role": "assistant", "content": "string"}
asst w/ tools : {"role": "assistant", "content": [{"type":"text","text":"..."},
                    {"type":"tool_use","id":"...","name":"...","input":{}}]}
tool results  : {"role": "user", "content": [{"type":"tool_result",
                    "tool_use_id":"...","content":"..."}]}
"""
import json


class Conversation:
    """Sliding-window conversation history (max_turns user-initiated turns)."""

    def __init__(self, max_turns=10):
        self.max_turns = max_turns
        # Raw message list in Anthropic format.
        self._msgs = []
        # Index into self._msgs where each *user-initiated* turn begins.
        # Tool-result messages are also role=="user" but are NOT turn starts.
        self._turn_starts = []

    # ── Write API ─────────────────────────────────────────────────────────────

    def add_user(self, text):
        """Add a user-initiated message and trim old turns if needed."""
        self._turn_starts.append(len(self._msgs))
        self._msgs.append({"role": "user", "content": text})
        self._trim()

    def add_assistant(self, text, tool_calls=None):
        """Add an assistant message (text-only or text+tool_calls).

        tool_calls: list of ToolCall objects (from llm.py).
        """
        if tool_calls:
            content = []
            if text:
                content.append({"type": "text", "text": text})
            for tc in tool_calls:
                content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                })
            self._msgs.append({"role": "assistant", "content": content})
        else:
            self._msgs.append({"role": "assistant", "content": text or ""})

    def add_tool_results(self, results):
        """Add tool results as a single user message.

        results: list of (tool_call_id, content_str) tuples.
        All results from one assistant response go in ONE user message —
        this is required by the Anthropic API.
        """
        self._msgs.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tc_id, "content": str(content)}
                for tc_id, content in results
            ],
        })

    # ── Read API ──────────────────────────────────────────────────────────────

    def build_messages(self, provider="anthropic"):
        """Return the message list ready for the given provider's API."""
        if provider == "anthropic":
            return list(self._msgs)
        return _to_openai(self._msgs)

    # ── Trim ──────────────────────────────────────────────────────────────────

    def _trim(self):
        """Remove oldest turns until turn count <= max_turns."""
        if len(self._turn_starts) <= self.max_turns:
            return
        n_drop = len(self._turn_starts) - self.max_turns
        cut_index = self._turn_starts[n_drop]
        self._msgs = self._msgs[cut_index:]
        self._turn_starts = [s - cut_index for s in self._turn_starts[n_drop:]]


# ── OpenAI format conversion ──────────────────────────────────────────────────

def _to_openai(msgs):
    """Convert Anthropic-format messages to OpenAI wire format."""
    result = []
    for m in msgs:
        role = m["role"]
        content = m["content"]

        if role == "user":
            if isinstance(content, str):
                result.append({"role": "user", "content": content})
            elif isinstance(content, list):
                for item in content:
                    if item.get("type") == "tool_result":
                        result.append({
                            "role": "tool",
                            "tool_call_id": item["tool_use_id"],
                            "content": item["content"],
                        })
                    elif item.get("type") == "text":
                        result.append({"role": "user", "content": item["text"]})

        elif role == "assistant":
            if isinstance(content, str):
                result.append({"role": "assistant", "content": content})
            elif isinstance(content, list):
                text_parts = [c["text"] for c in content if c.get("type") == "text"]
                tool_uses = [c for c in content if c.get("type") == "tool_use"]
                msg = {
                    "role": "assistant",
                    "content": " ".join(text_parts) if text_parts else None,
                }
                if tool_uses:
                    msg["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["input"]),
                            },
                        }
                        for tc in tool_uses
                    ]
                result.append(msg)

    return result
