"""Running commands and checking what goes on their command line."""

import os
import re
import subprocess

from fastapi import HTTPException

# Postfix tools treat a leading "-" as an option, and postsuper treats "ALL" as every message.
DOMAIN = re.compile(r"(?:(?!-)[a-z0-9-]{1,63}(?<!-)\.)+[a-z]{2,63}")
SELECTOR = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")
EMAIL = re.compile(r"[\w+=%'][\w.+=%'-]{0,63}@" + DOMAIN.pattern, re.ASCII)
QUEUE_ID = re.compile(r"[0-9A-Za-z]{6,20}")
MESSAGE_ID = re.compile(r"[\w.%+=-]{1,200}@[A-Za-z0-9.-]{1,253}", re.ASCII)
HEADER_NAME = re.compile(r"[A-Za-z0-9-]{1,76}")


def check(pattern: re.Pattern, value: str, what: str) -> str:
    """For path/query params: 422 unless `value` fully matches `pattern`."""
    if not pattern.fullmatch(value) or value.upper() == "ALL":
        raise HTTPException(422, f"invalid {what}: {value!r}")
    return value


def run(*argv: str, stdin: bytes | None = None, ok: tuple[int, ...] = (0,)) -> str:
    """Run a command (argv list, never a shell). Returns stdout + stderr."""
    try:
        p = subprocess.run(argv, input=stdin, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(502, f"{argv[0]}: {exc}")
    out = (p.stdout + p.stderr).decode(errors="replace").strip()
    if p.returncode not in ok:
        raise HTTPException(502, f"{os.path.basename(argv[0])} failed: {out}")
    return out
