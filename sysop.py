#!/usr/bin/env python3
"""sysop — lightweight Linux sysadmin assistant.

Usage:
  sysop.py              Start interactive session
  sysop.py --setup      Re-run configuration wizard
  sysop.py --version    Show version
"""
import json
import os
import sys

# Ensure lib/ is importable regardless of invocation path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.config import load_config, run_setup_wizard
from lib.conversation import Conversation
from lib.distro import detect_distro
from lib.llm import LLMClient
from lib.tools import ToolExecutor
from lib.soul import build_system_prompt
from lib.soul_gen import generate as generate_soul
from lib.ui import colored, setup_readline, print_banner, print_tool_call, print_tool_result

VERSION = "0.1.0"
MAX_TOOL_ITERATIONS = 20


def main():
    args = sys.argv[1:]
    if "--version" in args:
        print("sysop {}".format(VERSION))
        sys.exit(0)

    setup_readline()
    distro = detect_distro()

    if "--setup" in args:
        run_setup_wizard()
        generate_soul()
        print("Setup complete. Run 'sysop' to start.")
        sys.exit(0)

    config = load_config()
    if config is None:
        print(colored("  No config found. Running setup wizard...\n", "yellow"))
        config = run_setup_wizard()

    system_prompt = build_system_prompt(config, distro)
    client = LLMClient(config)
    tools = ToolExecutor(config, distro)
    convo = Conversation(max_turns=10)
    provider = config.get("provider", "anthropic")

    print_banner(config, distro)

    while True:
        try:
            user_input = input(colored("you> ", "green")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n" + colored("Bye.", "dim"))
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "bye", "q"):
            print(colored("Bye.", "dim"))
            break

        if user_input == "--setup":
            config = run_setup_wizard()
            generate_soul()
            client = LLMClient(config)
            tools = ToolExecutor(config, distro)
            provider = config.get("provider", "anthropic")
            system_prompt = build_system_prompt(config, distro)
            print(colored("Config updated.", "green"))
            continue

        try:
            print(colored("  (Ctrl+C to stop)", "dim"), end="\r", flush=True)
            _run_agent_turn(client, tools, convo, user_input, system_prompt, provider)
            print("                      ", end="\r")  # clear hint line
        except RuntimeError as e:
            print("\n" + colored("Error: {}".format(e), "red"))
            convo.add_user(user_input)
            convo.add_assistant("[error: {}]".format(e))
        except KeyboardInterrupt:
            print("\n" + colored("(interrupted)", "dim"))
            convo.add_user(user_input)
            convo.add_assistant("[interrupted]")

    print()


def _run_agent_turn(client, tools, convo, user_input, system_prompt, provider):
    """Run the full LLM + tool loop for one user message.

    Maintains a local growing message list so the API sees the full tool
    call history within a turn, then commits the complete turn to convo.
    """
    # History from committed turns + the new user message.
    messages = convo.build_messages(provider)
    messages.append({"role": "user", "content": user_input})

    tool_defs = tools.definitions()
    all_tool_exchanges = []  # (ToolCall, result) pairs for this turn

    for iteration in range(MAX_TOOL_ITERATIONS + 1):
        if iteration == MAX_TOOL_ITERATIONS:
            msg = "[Hit max tool iterations ({}). Stopping.]".format(MAX_TOOL_ITERATIONS)
            print(colored(msg, "yellow"))
            _commit_turn(convo, user_input, all_tool_exchanges, msg)
            return

        response = client.chat(messages, tool_defs, system_prompt)

        if not response.tool_calls:
            # Text-only response — commit and done.
            _commit_turn(convo, user_input, all_tool_exchanges, response.text)
            return

        # Append the assistant's tool-use message to the local list.
        messages.append(_assistant_tool_msg(response, provider))

        # Execute tools, collect results.
        tool_results = []
        for tc in response.tool_calls:
            args_preview = ", ".join(
                "{}={!r}".format(k, str(v)[:80])
                for k, v in (tc.arguments or {}).items()
            )
            print_tool_call(tc.name, args_preview)
            result = tools.execute(tc.name, tc.arguments or {})
            print_tool_result(result)
            all_tool_exchanges.append((tc, result))
            tool_results.append((tc, result))

        # Append tool results to the local message list.
        _append_tool_results(messages, tool_results, provider)


def _commit_turn(convo, user_input, tool_exchanges, assistant_text):
    """Commit a completed turn to the conversation history.

    Full tool output is shown on screen but only a short excerpt is stored in
    history to keep context-window token usage low.
    """
    convo.add_user(user_input)
    if tool_exchanges:
        tcs = [tc for tc, _ in tool_exchanges]
        convo.add_assistant("", tcs)
        convo.add_tool_results([
            (tc.id, _trim_for_history(result))
            for tc, result in tool_exchanges
        ])
    convo.add_assistant(assistant_text)


def _trim_for_history(text, limit=600):
    """Return a short excerpt of tool output suitable for storing in history."""
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n…[truncated]…\n" + text[-half:]


def _assistant_tool_msg(response, provider):
    """Build the assistant message dict with tool_use/tool_calls blocks."""
    if provider == "anthropic":
        content = []
        # Thinking blocks MUST precede text/tool_use in the same message so the
        # Anthropic API can track per-turn reasoning continuity.
        for tb in getattr(response, "thinking_blocks", []):
            content.append(tb)
        if response.text:
            content.append({"type": "text", "text": response.text})
        for tc in response.tool_calls:
            content.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.arguments or {},
            })
        return {"role": "assistant", "content": content}
    else:
        tc_list = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments or {}),
                },
            }
            for tc in response.tool_calls
        ]
        msg = {"role": "assistant", "tool_calls": tc_list}
        if response.text:
            msg["content"] = response.text
        return msg


def _append_tool_results(messages, tool_results, provider):
    """Append tool result messages to the message list."""
    if provider == "anthropic":
        # Batch all results into one user message.
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result,
                }
                for tc, result in tool_results
            ],
        })
    else:
        # OpenAI: one message per tool result.
        for tc, result in tool_results:
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })


if __name__ == "__main__":
    main()
