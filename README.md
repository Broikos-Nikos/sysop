# sysop

A lightweight Linux sysadmin assistant for the terminal. Runs on Raspbian, Ubuntu, and Fedora with zero dependencies beyond Python 3.

**Examples of what you can ask:**
- *install python*
- *uninstall all text editors, install sublime and make it default*
- *overclock raspberry pi 5*
- *create a cronjob that cleans /tmp every night at 3am*
- *why is my disk full*

## Install / Update

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Broikos-Nikos/sysop/main/install.sh)
```

Run the same command to update. No git required on the target machine.

## First run

```bash
sysop
```

The setup wizard runs automatically on first launch. It will ask for:

1. **Provider** — Anthropic (Claude) or OpenAI (GPT)
2. **Model** — pick from a list
3. **API key** — validated before saving
4. **Extended thinking** — shows model reasoning in real time (Anthropic only)
5. **Sudo password** — saved locally so the agent can run privileged commands without prompting

Config is stored at `~/.config/sysop/config.json` with `0600` permissions.

To re-run the wizard at any time:

```bash
sysop --setup
```

## Features

- **Zero friction** — executes commands immediately, no confirmations
- **Correct package manager** — auto-detects `apt`, `dnf`, `pacman`, etc.
- **Sudo without prompting** — password stored in config, injected silently
- **Extended thinking** — streams Claude's reasoning to the terminal in real time
- **10-turn memory** — keeps recent context, trims old turns to stay lean
- **Ctrl+C** — stop the agent mid-run at any time

## Requirements

- Python 3.8+ (pre-installed on all target distros)
- `curl` or `wget` (for install only)
- An [Anthropic](https://console.anthropic.com/settings/keys) or [OpenAI](https://platform.openai.com/api-keys) API key
