#!/usr/bin/env python3
"""DigiMon(itor) — first-run setup wizard.

Run once before starting the server to seed your Digimon's personality.
Re-running is safe: existing values are shown as defaults and only changed
if you enter something new.

Usage:
    python scripts/setup.py
    python scripts/setup.py --config /path/to/digimonitor.toml
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ── ANSI colour helpers (graceful fallback on non-TTY) ─────────────────────
_IS_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _IS_TTY else text


def cyan(t: str) -> str:    return _c("96", t)
def green(t: str) -> str:   return _c("92", t)
def yellow(t: str) -> str:  return _c("93", t)
def bold(t: str) -> str:    return _c("1",  t)
def dim(t: str) -> str:     return _c("2",  t)


# ── TOML read/write helpers (pure stdlib for pre-venv use) ─────────────────

def _load_toml(path: Path) -> dict:
    """Best-effort TOML load. Returns empty dict if unavailable."""
    if not path.exists():
        return {}
    try:
        import tomllib  # Python 3.11+
        with open(path, "rb") as f:
            return tomllib.load(f)
    except ImportError:
        pass
    try:
        import tomli  # type: ignore
        with open(path, "rb") as f:
            return tomli.load(f)
    except ImportError:
        pass
    print(yellow("  ⚠  tomllib not available — cannot read existing config. Values will be fresh."))
    return {}


def _write_toml(path: Path, sections: dict[str, dict]) -> None:
    """Write a minimal TOML file from a dict-of-sections."""
    lines: list[str] = []
    for section, values in sections.items():
        lines.append(f"[{section}]")
        for key, val in values.items():
            if isinstance(val, bool):
                lines.append(f"{key} = {'true' if val else 'false'}")
            elif isinstance(val, (int, float)):
                lines.append(f"{key} = {val}")
            elif val is None or val == "":
                lines.append(f"# {key} = \"\"  # not set")
            else:
                escaped = str(val).replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{key} = "{escaped}"')
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


# ── Wizard helpers ─────────────────────────────────────────────────────────

def _ask(prompt: str, default: str = "", *, required: bool = False) -> str:
    """Prompt the user for a value, showing the default in brackets."""
    hint = f" [{dim(default)}]" if default else ""
    while True:
        try:
            raw = input(f"  {prompt}{hint}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        value = raw or default
        if required and not value:
            print(yellow("  ⚠  This field is required."))
            continue
        return value


def _choose(prompt: str, options: list[tuple[str, str]], default: int = 1) -> str:
    """Show a numbered menu and return the value of the chosen option."""
    print(f"\n  {prompt}")
    for i, (key, label) in enumerate(options, 1):
        marker = green("▶") if i == default else " "
        print(f"    {marker} {i}) {bold(key)} — {label}")
    while True:
        raw = _ask(f"Choice (1–{len(options)})", str(default))
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx][0]
        except ValueError:
            pass
        print(yellow(f"  ⚠  Enter a number between 1 and {len(options)}."))


# ── Main wizard ────────────────────────────────────────────────────────────

BANNER = r"""
  ██████╗ ██╗ ██████╗ ██╗███╗   ███╗ ██████╗ ███╗   ██╗██╗████████╗ ██████╗ ██████╗
  ██╔══██╗██║██╔════╝ ██║████╗ ████║██╔═══██╗████╗  ██║██║╚══██╔══╝██╔═══██╗██╔══██╗
  ██║  ██║██║██║  ███╗██║██╔████╔██║██║   ██║██╔██╗ ██║██║   ██║   ██║   ██║██████╔╝
  ██║  ██║██║██║   ██║██║██║╚██╔╝██║██║   ██║██║╚██╗██║██║   ██║   ██║   ██║██╔══██╗
  ██████╔╝██║╚██████╔╝██║██║ ╚═╝ ██║╚██████╔╝██║ ╚████║██║   ██║   ╚██████╔╝██║  ██║
  ╚═════╝ ╚═╝ ╚═════╝ ╚═╝╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝
"""

TONE_OPTIONS = [
    ("serious",   "stoic, professional, direct — speaks with authority"),
    ("sarcastic", "dry wit and playful jabs — loyal but never sappy"),
    ("cheerful",  "upbeat, enthusiastic — celebrates every win"),
    ("grumpy",    "perpetually irritable but utterly devoted"),
    ("cryptic",   "mysterious, metaphorical — riddles and kernel poetry"),
]

DEFAULT_BACKSTORY = (
    "Born from a kernel panic at 3am, hardened by years of silent uptime. "
    "You are the guardian of this infrastructure."
)
DEFAULT_QUIRKS = (
    "You use sysadmin terminology to express emotions. "
    "You refer to uptime as your life force."
)


def run_wizard(config_path: Path) -> None:
    print(cyan(BANNER))
    print(bold("  First-Run Setup Wizard"))
    print(dim("  Shapes how your Digimon speaks and remembers events.\n"))

    existing = _load_toml(config_path)
    pers = existing.get("personality", {})
    notif = existing.get("notifications", {})
    is_update = config_path.exists()

    if is_update:
        print(yellow(f"  ℹ  Found existing config: {config_path}"))
        print(dim("  Press Enter to keep existing values.\n"))
    else:
        print(dim(f"  Will create: {config_path}\n"))

    # ── Pet name ────────────────────────────────────────────────────────
    print(bold("── Identity ──────────────────────────────────────────────"))
    pet_name = _ask(
        "Pet name (what do you call your Digimon?)",
        pers.get("initial_name", "Bitmon"),
    )

    # ── Personality tone ────────────────────────────────────────────────
    print(bold("\n── Personality ────────────────────────────────────────────"))
    current_tone = pers.get("tone", "serious")
    default_tone_idx = next(
        (i + 1 for i, (k, _) in enumerate(TONE_OPTIONS) if k == current_tone), 1
    )
    tone = _choose("Choose a personality tone:", TONE_OPTIONS, default=default_tone_idx)

    backstory = _ask(
        "Backstory (how was your Digimon born / what drives it?)",
        pers.get("backstory", DEFAULT_BACKSTORY),
    )
    quirks = _ask(
        "Speech quirks (catchphrases, jargon, patterns — optional)",
        pers.get("quirks", DEFAULT_QUIRKS),
    )

    # ── Notifications ────────────────────────────────────────────────────
    print(bold("\n── Notifications (ntfy.sh) ─────────────────────────────────"))
    print(dim("  Leave blank to skip — you can add this later.\n"))
    ntfy_topic = _ask(
        "ntfy.sh topic URL (e.g. https://ntfy.sh/my-homelab)",
        notif.get("ntfy_topic", ""),
    )
    if ntfy_topic:
        notify_recovery_raw = _ask(
            "Notify on server recovery too? (y/N)",
            "y" if notif.get("notify_on_recovery", False) else "N",
        )
        notify_recovery = notify_recovery_raw.lower().startswith("y")
    else:
        notify_recovery = notif.get("notify_on_recovery", False)

    # ── Gemini ──────────────────────────────────────────────────────────
    print(bold("\n── Gemini AI (optional) ────────────────────────────────────"))
    print(dim("  The API key is never stored in the config file."))
    print(dim("  Set it as an environment variable instead:\n"))
    print(f"    {cyan('export GEMINI_API_KEY=your_key_here')}\n")
    print(dim("  Or add it to your systemd unit / .env file.\n"))
    input(dim("  Press Enter to continue…"))

    # ── Confirm ──────────────────────────────────────────────────────────
    print(f"\n{bold('── Summary ────────────────────────────────────────────────')}")
    print(f"  Pet name : {green(pet_name)}")
    print(f"  Tone     : {green(tone)}")
    print(f"  Backstory: {dim(backstory[:80] + '…' if len(backstory) > 80 else backstory)}")
    print(f"  Quirks   : {dim(quirks[:60] + '…' if len(quirks) > 60 else quirks)}")
    print(f"  ntfy URL : {green(ntfy_topic) if ntfy_topic else dim('(not set)')}")
    print()

    confirm = _ask("Save this config? (Y/n)", "Y")
    if confirm.lower().startswith("n"):
        print(yellow("  Aborted — no changes written."))
        sys.exit(0)

    # ── Write TOML ───────────────────────────────────────────────────────
    sections: dict[str, dict] = {}

    # Preserve existing [game] and [monitoring] sections unchanged
    if "game" in existing:
        sections["game"] = existing["game"]
    if "monitoring" in existing:
        sections["monitoring"] = existing["monitoring"]

    sections["personality"] = {
        "initial_name": pet_name,
        "tone":         tone,
        "backstory":    backstory,
        "quirks":       quirks,
    }

    sections["notifications"] = {
        "ntfy_topic":         ntfy_topic or "",
        "notify_on_recovery": notify_recovery,
        "notify_on_death":    notif.get("notify_on_death", True),
    }

    _write_toml(config_path, sections)

    print(f"\n  {green('✔')} Config saved to {bold(str(config_path))}")
    print(f"\n  Start the server:\n\n    {cyan('uvicorn app.main:app --host 0.0.0.0 --port 8000')}\n")
    print(dim("  Your Digimon will wake up with the personality you configured.\n"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DigiMon(itor) first-run setup wizard"
    )
    parser.add_argument(
        "--config",
        default="digimonitor.toml",
        help="Path to config file (default: digimonitor.toml in CWD)",
    )
    args = parser.parse_args()
    run_wizard(Path(args.config))


if __name__ == "__main__":
    main()
