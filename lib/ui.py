"""Terminal formatting — ANSI colors, readline, output helpers."""
import sys
import os
import atexit

COLORS = {
    "red": "\033[0;31m",
    "green": "\033[0;32m",
    "yellow": "\033[1;33m",
    "blue": "\033[0;34m",
    "cyan": "\033[0;36m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "reset": "\033[0m",
}

_is_tty = sys.stdout.isatty()


def colored(text, color):
    if not _is_tty:
        return text
    return "{}{}{}".format(COLORS.get(color, ""), text, COLORS["reset"])


def setup_readline():
    try:
        import readline
    except ImportError:
        return
    history_dir = os.path.expanduser("~/.config/sysop")
    os.makedirs(history_dir, exist_ok=True)
    history_path = os.path.join(history_dir, "input_history")
    try:
        readline.read_history_file(history_path)
    except (FileNotFoundError, OSError):
        pass
    readline.set_history_length(500)
    atexit.register(readline.write_history_file, history_path)


def print_banner(config, distro):
    model = config.get("model", "unknown")
    provider = config.get("provider", "unknown")
    lines = [
        "",
        "  sysop — Linux assistant",
        "  Model: {} ({})".format(model, provider),
        "  {}  |  {}  |  {}".format(distro.name, distro.pkg_manager, distro.arch),
        "  Type 'exit' to quit, '--setup' to reconfigure.",
        "",
    ]
    print(colored("\n".join(lines), "dim"))


def print_tool_call(name, args_summary):
    print(colored("  [{}] ".format(name), "yellow") + colored(args_summary, "dim"))


def print_tool_result(output):
    lines = output.strip().split("\n")
    if len(lines) > 15:
        preview = "\n".join(lines[:6]) + "\n  ... ({} more lines) ...\n".format(
            len(lines) - 12
        ) + "\n".join(lines[-6:])
    else:
        preview = output.strip()
    for line in preview.split("\n"):
        print(colored("  | ", "dim") + line)
