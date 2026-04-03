"""Config loading, saving, and setup wizard."""
import json
import os
import stat
import sys
import subprocess
import urllib.request
import urllib.error
import ssl
import getpass

CONFIG_PATH = os.path.expanduser("~/.config/sysop/config.json")

# Model choices per provider (label, model_id).
ANTHROPIC_MODELS = [
    ("claude-sonnet-4-5 (recommended — fast + capable)", "claude-sonnet-4-5-20251001"),
    ("claude-haiku-4-5 (lightweight, cheaper)", "claude-haiku-4-5-20251001"),
    ("claude-opus-4 (overkill + expensive)", "claude-opus-4-20250514"),
]
OPENAI_MODELS = [
    ("gpt-5.3-codex (recommended — code-focused)", "gpt-5.3-codex"),
    ("gpt-5.3 (stable)", "gpt-5.3"),
    ("gpt-5.4 (overkill + expensive)", "gpt-5.4"),
    ("gpt-4.1 (previous gen)", "gpt-4.1"),
    ("gpt-4.1-mini (lightweight, cheaper)", "gpt-4.1-mini"),
]


def load_config(path=None):
    """Load config from disk. Returns dict or None if not found/invalid."""
    p = path or CONFIG_PATH
    try:
        with open(p) as f:
            cfg = json.load(f)
        if cfg.get("api_key") and cfg.get("model") and cfg.get("provider"):
            return cfg
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None


def save_config(cfg, path=None):
    """Save config with 0600 permissions."""
    p = path or CONFIG_PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)


def _prompt(msg, default=None):
    if default:
        display = "{} [{}]: ".format(msg, default)
    else:
        display = "{}: ".format(msg)
    try:
        val = input(display).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled.")
        sys.exit(0)
    return val if val else default


def _pick(options, prompt="Choice"):
    """Display a numbered menu and return the chosen index (0-based)."""
    for i, (label, _) in enumerate(options, 1):
        print("  [{}] {}".format(i, label))
    while True:
        raw = _prompt(prompt, "1")
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return idx
        except (TypeError, ValueError):
            pass
        print("  Invalid — enter a number 1-{}.".format(len(options)))


def _validate_key(provider, api_key, model):
    """Make a minimal API call to verify the key. Returns (ok, error_msg)."""
    try:
        if provider == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            body = json.dumps({
                "model": model, "max_tokens": 10,
                "messages": [{"role": "user", "content": "hi"}],
            }).encode()
            headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }
        else:
            url = "https://api.openai.com/v1/chat/completions"
            body = json.dumps({
                "model": model, "max_tokens": 10,
                "messages": [{"role": "user", "content": "hi"}],
            }).encode()
            headers = {
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(api_key),
            }
        req = urllib.request.Request(url, data=body, headers=headers)
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            resp.read()
        return True, ""
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "Invalid API key (401 Unauthorized)"
        if e.code == 404:
            return False, "Model not found: {}".format(model)
        return False, "HTTP {}: {}".format(e.code, e.reason)
    except Exception as e:
        return False, str(e)


def _validate_sudo_password(password):
    """Test the password against sudo. Returns True if accepted."""
    try:
        r = subprocess.run(
            ["sudo", "-kS", "true"],
            input=(password + "\n").encode(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def _ensure_path():
    """Add ~/.local/bin to PATH in shell rc if not already there."""
    bin_dir = os.path.expanduser("~/.local/bin")
    if bin_dir in os.environ.get("PATH", "").split(":"):
        return
    for rc in ["~/.bashrc", "~/.zshrc", "~/.profile"]:
        rc_path = os.path.expanduser(rc)
        if not os.path.exists(rc_path):
            continue
        with open(rc_path) as f:
            content = f.read()
        if ".local/bin" in content:
            return
        with open(rc_path, "a") as f:
            f.write('\nexport PATH="$HOME/.local/bin:$PATH"  # sysop\n')
        print('\n  Added ~/.local/bin to PATH in {}'.format(rc_path))
        print('  Run: source {}'.format(rc_path))
        return
    print('\n  Note: add ~/.local/bin to your PATH to run sysop from anywhere.')


def run_setup_wizard(path=None):
    """Interactive setup wizard. Returns saved config dict."""
    print("\n  sysop — setup")
    print("  " + "─" * 30)

    # ── 1. Provider ──────────────────────────────────────────────────────────
    print("\n  1. Provider:")
    providers = [("Anthropic (Claude)", "anthropic"), ("OpenAI (GPT)", "openai")]
    idx = _pick(providers)
    provider_id = providers[idx][1]
    print("  -> {}".format(providers[idx][0]))

    # ── 2. Model ─────────────────────────────────────────────────────────────
    models = ANTHROPIC_MODELS if provider_id == "anthropic" else OPENAI_MODELS
    print("\n  2. Model:")
    mi = _pick(models)
    model = models[mi][1]
    print("  -> {}".format(model))

    # ── 3. API key (loop until valid, 3 attempts then offer to save anyway) ──
    if provider_id == "anthropic":
        print("\n  3. Anthropic API key  (console.anthropic.com/settings/keys)")
    else:
        print("\n  3. OpenAI API key  (platform.openai.com/api-keys)")

    api_key = None
    for attempt in range(1, 4):
        raw = getpass.getpass("     Key: ").strip()
        if not raw:
            print("     Cannot be empty.")
            continue
        print("     Validating...", end=" ", flush=True)
        ok, err = _validate_key(provider_id, raw, model)
        if ok:
            print("OK")
            api_key = raw
            break
        print("FAILED — {}".format(err))
        if attempt < 3:
            print("     Try again ({}/3).".format(attempt))
        else:
            ans = _prompt("     Save anyway and fix later?", "n").lower()
            if ans in ("y", "yes"):
                api_key = raw
            else:
                print("\n  Setup cancelled.")
                sys.exit(0)

    # ── 4. Extended thinking (Anthropic only) ────────────────────────────────
    extended_thinking = False
    if provider_id == "anthropic":
        print("\n  4. Extended thinking")
        print("     Shows model reasoning in real time. Adds a few seconds per response.")
        ans = _prompt("     Enable?", "y").lower()
        extended_thinking = ans in ("y", "yes", "")

    # ── 5. Sudo password ─────────────────────────────────────────────────────
    print("\n  5. Sudo password")
    print("     Stored locally so the agent can run privileged commands without prompting.")
    ans = _prompt("     Save sudo password?", "y").lower()
    sudo_password = ""
    if ans in ("y", "yes", ""):
        while True:
            pwd = getpass.getpass("     Password: ").strip()
            if not pwd:
                print("     Skipped.")
                break
            print("     Verifying...", end=" ", flush=True)
            if _validate_sudo_password(pwd):
                print("OK")
                sudo_password = pwd
                break
            print("FAILED — wrong password or sudo unavailable. Try again.")

    # ── PATH ─────────────────────────────────────────────────────────────────
    _ensure_path()

    cfg = {
        "provider": provider_id,
        "model": model,
        "api_key": api_key,
        "max_command_timeout": 120,
        "sudo_password": sudo_password,
        "extended_thinking": extended_thinking,
    }
    save_config(cfg, path)
    print("\n  Config saved to {}\n".format(path or CONFIG_PATH))
    return cfg
