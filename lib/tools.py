"""6 tool definitions + execution engine."""
import os
import re
import subprocess

from . import safety

# ── Tool JSON schemas (Anthropic format) ──────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "run_command",
        "description": (
            "Execute a shell command via bash. Returns stdout, stderr, and exit code. "
            "Commands run as the current user. Prefix with 'sudo' for privileged operations. "
            "Use this for everything: installing packages, managing services, editing config "
            "files the hard way, network ops, cron, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Bash command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max seconds to wait (default: configured timeout).",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read a file and return its contents. "
            "Use start_line/end_line to read a section of a large file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative file path."},
                "start_line": {"type": "integer", "description": "Start line (1-based, inclusive)."},
                "end_line": {"type": "integer", "description": "End line (1-based, inclusive)."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write content to a file, creating parent directories as needed. "
            "Overwrites the file if it already exists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "patch_file",
        "description": (
            "Find and replace text in a file. Safer than write_file when editing config files "
            "because it only changes the targeted section. The match must be exact."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {
                    "type": "string",
                    "description": "The exact text to find (including whitespace).",
                },
                "new_text": {"type": "string", "description": "Replacement text."},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "list_directory",
        "description": "List files and directories at a path with type indicators (file/dir/link).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path. Defaults to current working directory.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "package_info",
        "description": (
            "Query the package manager for read-only information. "
            "Actions: 'search' (find packages by name/keyword), "
            "'info' (details about a specific package), "
            "'list_installed' (all installed packages, optionally grep'd by filter). "
            "To actually install/remove packages, use run_command."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["search", "info", "list_installed"],
                },
                "package": {
                    "type": "string",
                    "description": "Package name or search term (required for search/info).",
                },
                "filter": {
                    "type": "string",
                    "description": "Optional grep filter for list_installed.",
                },
            },
            "required": ["action"],
        },
    },
]


# ── Executor ──────────────────────────────────────────────────────────────────

class ToolExecutor:
    MAX_OUTPUT = 15_000  # chars before head+tail truncation

    def __init__(self, config, distro):
        self.config = config
        self.distro = distro
        self._default_timeout = config.get("max_command_timeout", 120)
        self._sudo_password = config.get("sudo_password", "")

    def definitions(self):
        return TOOL_DEFINITIONS

    def execute(self, name, arguments):
        """Dispatch tool call and return result string (already safety-processed)."""
        try:
            if name == "run_command":
                result = self._run_command(
                    arguments["command"],
                    arguments.get("timeout", self._default_timeout),
                )
            elif name == "read_file":
                result = self._read_file(
                    arguments["path"],
                    arguments.get("start_line"),
                    arguments.get("end_line"),
                )
            elif name == "write_file":
                result = self._write_file(arguments["path"], arguments["content"])
            elif name == "patch_file":
                result = self._patch_file(
                    arguments["path"], arguments["old_text"], arguments["new_text"]
                )
            elif name == "list_directory":
                result = self._list_directory(arguments.get("path", "."))
            elif name == "package_info":
                result = self._package_info(
                    arguments["action"],
                    arguments.get("package", ""),
                    arguments.get("filter", ""),
                )
            else:
                result = "Unknown tool: {}".format(name)
        except KeyError as e:
            result = "Missing required argument: {}".format(e)
        except Exception as e:
            result = "Tool error: {}".format(e)

        # Apply output safety: strip ANSI, check for prompt injection.
        result = safety.sanitize_output(result)
        result = safety.tag_if_suspicious(result)
        return result

    # ── Tool implementations ───────────────────────────────────────────────────

    _SUDO_RE = re.compile(r'\bsudo\b')

    def _run_command(self, command, timeout):
        blocked, reason = safety.check_command(command)
        if blocked:
            return "BLOCKED: {} — this command is permanently disabled.".format(reason)

        # If the command uses sudo and we have a stored password, inject it via
        # `sudo -S` (reads password from stdin) to avoid interactive prompts.
        stdin_data = None
        run_cmd = command
        if self._sudo_password and self._SUDO_RE.search(command):
            run_cmd = self._SUDO_RE.sub("sudo -S", command, count=1)
            stdin_data = (self._sudo_password + "\n").encode()

        try:
            proc = subprocess.Popen(
                ["bash", "-c", run_cmd],
                stdin=subprocess.PIPE if stdin_data else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.getcwd(),
            )
            try:
                stdout_b, stderr_b = proc.communicate(input=stdin_data,
                                                       timeout=int(timeout))
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                return "Command timed out after {}s.".format(timeout)

            stdout = stdout_b.decode("utf-8", errors="replace")
            stderr = stderr_b.decode("utf-8", errors="replace")
            # Strip the sudo password prompt line from stderr (sudo -S emits it).
            if stdin_data:
                stderr = "\n".join(
                    l for l in stderr.splitlines()
                    if not l.startswith("[sudo]") and "password" not in l.lower()
                )
            parts = []
            if stdout:
                parts.append(stdout)
            if stderr:
                parts.append("[stderr]\n" + stderr)
            parts.append("[exit {}]".format(proc.returncode))
            output = "\n".join(parts)
        except Exception as e:
            return "Failed to run command: {}".format(e)

        return self._truncate(output)

    def _read_file(self, path, start_line, end_line):
        try:
            with open(os.path.expanduser(path)) as f:
                lines = f.readlines()
        except (FileNotFoundError, PermissionError) as e:
            return "Error: {}".format(e)

        if start_line is not None:
            s = max(0, int(start_line) - 1)
            e_ = int(end_line) if end_line is not None else len(lines)
            lines = lines[s:e_]
            offset = int(start_line)
        else:
            offset = 1

        numbered = "".join(
            "{:4d} | {}".format(i + offset, l)
            for i, l in enumerate(lines)
        )
        return self._truncate(numbered)

    def _write_file(self, path, content):
        path = os.path.expanduser(path)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return "Written {} bytes to {}.".format(len(content), path)

    def _patch_file(self, path, old_text, new_text):
        path = os.path.expanduser(path)
        try:
            with open(path) as f:
                content = f.read()
        except (FileNotFoundError, PermissionError) as e:
            return "Error: {}".format(e)

        if old_text not in content:
            return "Error: old_text not found in {}. The patch was not applied.".format(path)

        new_content = content.replace(old_text, new_text, 1)
        with open(path, "w") as f:
            f.write(new_content)
        return "Patched {}.".format(path)

    def _list_directory(self, path):
        path = os.path.expanduser(path)
        try:
            entries = os.scandir(path)
            lines = []
            for e in sorted(entries, key=lambda x: (not x.is_dir(), x.name.lower())):
                if e.is_dir(follow_symlinks=False):
                    kind = "dir"
                elif e.is_symlink():
                    kind = "link"
                else:
                    kind = "file"
                lines.append("[{}] {}".format(kind, e.name))
            return "\n".join(lines) if lines else "(empty directory)"
        except PermissionError:
            return "Permission denied: {}".format(path)
        except FileNotFoundError:
            return "Not found: {}".format(path)

    def _package_info(self, action, package, filter_str):
        d = self.distro
        if action == "search":
            if not package:
                return "Error: 'package' is required for search."
            cmd = d.pkg_search.format(package) if "{}" in d.pkg_search else "{} {}".format(d.pkg_search, package)
        elif action == "info":
            if not package:
                return "Error: 'package' is required for info."
            # Most package managers accept 'show' or 'info'.
            if d.pkg_manager == "apt":
                cmd = "apt show {}".format(package)
            elif d.pkg_manager in ("dnf", "yum"):
                cmd = "{} info {}".format(d.pkg_manager, package)
            elif d.pkg_manager == "pacman":
                cmd = "pacman -Si {}".format(package)
            elif d.pkg_manager == "zypper":
                cmd = "zypper info {}".format(package)
            elif d.pkg_manager == "apk":
                cmd = "apk info {}".format(package)
            else:
                cmd = "echo 'Package manager {} does not support info'".format(d.pkg_manager)
        elif action == "list_installed":
            cmd = d.pkg_list
            if filter_str:
                cmd = "{} | grep -i {}".format(cmd, filter_str)
        else:
            return "Unknown action: {}".format(action)

        return self._run_command(cmd, 30)

    def _truncate(self, text):
        limit = self.MAX_OUTPUT
        if len(text) <= limit:
            return text
        head = text[:limit // 2]
        tail = text[-(limit // 2):]
        skipped = len(text) - limit
        return "{}\n\n... [{} chars truncated] ...\n\n{}".format(head, skipped, tail)
