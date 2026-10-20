"""MCP server `charts`: runs pandas/matplotlib code in a subprocess with a read-only DB and no API keys."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from flatmarket import db

mcp = FastMCP("charts")
TIMEOUT_S = 60
MAX_OUTPUT = 4000
IMAGE_SUFFIXES = {".png", ".svg", ".jpg"}
_PASS_ENV = ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL")

PRELUDE = '''\
import os, sqlite3
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
DB = sqlite3.connect(os.environ["FLATS_DB_URI"], uri=True)
OUT = Path(os.environ["REPORT_DIR"])
'''


def report_dir() -> Path:
    p = Path(os.getenv("REPORT_DIR", "reports/latest")).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _tail(s: str) -> str:
    return s if len(s) <= MAX_OUTPUT else "...(truncated)...\n" + s[-MAX_OUTPUT:]


@mcp.tool()
def run_python(code: str) -> dict:
    """Run Python code for analysis and charts. Already defined: `pd` (pandas), `plt` (matplotlib, Agg backend),
    `DB` (read-only sqlite3 connection to table `flats`, e.g. `pd.read_sql("SELECT ... FROM flats", DB)`) and
    `OUT` (pathlib.Path of the report folder). Save every chart with `plt.savefig(OUT / "name.png", dpi=120,
    bbox_inches="tight")` then `plt.close()`. Use print() for numbers you need. Timeout 60 s.
    Returns exit code, stdout/stderr and the image files created by this call.
    """
    if not db.path().exists():
        return {"exit_code": None, "error": f"{db.path()} does not exist yet; run Agent A first", "files": []}
    out = report_dir()
    before = {p.name: p.stat().st_mtime for p in out.iterdir()}
    env = {k: os.environ[k] for k in _PASS_ENV if k in os.environ}
    env.update(FLATS_DB_URI=db.path().as_uri() + "?mode=ro", REPORT_DIR=str(out), MPLBACKEND="Agg",
               PYTHONIOENCODING="utf-8", MPLCONFIGDIR=str(Path(tempfile.gettempdir()) / "flatmarket-mpl"))
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "job.py"
        script.write_text(PRELUDE + code, encoding="utf-8")
        try:
            proc = subprocess.run([sys.executable, str(script)], cwd=out, env=env, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return {"exit_code": None, "error": f"timed out after {TIMEOUT_S} s", "files": []}
    files = sorted(p.name for p in out.iterdir()
                   if p.suffix.lower() in IMAGE_SUFFIXES and before.get(p.name) != p.stat().st_mtime)
    return {"exit_code": proc.returncode, "stdout": _tail(proc.stdout), "stderr": _tail(proc.stderr),
            "files": files}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
