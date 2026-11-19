"""Domain driver: linear_algebra_ode skill (SymPy-first) -> HTML/MathML -> PDF.

Usage:
  python run_domain.py <input.md> <out_dir> [--title T] [--student S] [--course C]

Stages (same numbering as the starter pipeline, so the two stay comparable):
  1_ingested.json   raw text + metadata
  2_parsed.json     problems detected by the stage-2 parser
  3_solutions.json  solutions from the deterministic SymPy kernel + oracles
  homework.html     self-contained MathML page
  homework.pdf      Edge/Chrome headless print (skipped when no browser)

Exit code: 0 all stages ok, 3 kernel stage failed, 4 render failed, 5 no PDF.
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import parse_problems as PP  # noqa: E402
import solve_kernel as K  # noqa: E402


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    opts = {}
    for i, a in enumerate(argv[1:]):
        if a.startswith("--") and i + 2 <= len(argv[1:]):
            opts[a[2:]] = argv[i + 2]
    if len(args) < 2:
        print("usage: python run_domain.py <input.md> <out_dir> [--title T]")
        return 1

    src_path = Path(args[0]).resolve()
    out_dir = Path(args[1]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = src_path.read_text(encoding="utf-8", errors="replace")

    stage1 = {
        "raw_text": raw,
        "text": raw,
        "source": src_path.name,
        "meta": {
            "chars": len(raw),
            "lines": raw.count("\n") + 1,
            "course": opts.get("course", ""),
            "student": opts.get("student", ""),
        },
    }
    _write_json(out_dir / "1_ingested.json", stage1)
    print("[stage1] chars=%d lines=%d" % (len(raw), stage1["meta"]["lines"]))

    parsed = PP.parse_problems(stage1)
    _write_json(out_dir / "2_parsed.json", parsed)
    print("[stage2] problems=%d" % len(parsed))

    solved = K.solve_document({"problems": parsed}, {"domain": "linear_algebra_ode"})
    _write_json(out_dir / "3_solutions.json", solved)
    meta = solved["meta"]
    print("[stage3] total=%d solved=%d unsolved=%d verify_ok=%d verify_fail=%d"
          % (meta["total"], meta["solved"], meta["unsolved"],
             meta["verify_ok"], meta["verify_fail"]))
    if meta["total"] == 0 or meta["solved"] == 0:
        print("[stage3] FAIL no solvable problem")
        return 3

    title = opts.get("title", src_path.stem)
    html_path = out_dir / "homework.html"
    pdf_path = out_dir / "homework.pdf"
    cmd = [sys.executable, str(HERE / "render_html_pdf.py"),
           str(out_dir / "3_solutions.json"), str(html_path), str(pdf_path),
           "--title", title]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=420)
    print("[stage4] rc=%d" % proc.returncode)
    for line in (proc.stdout or "").splitlines():
        print("   " + line)
    err = (proc.stderr or "").strip().splitlines()
    if err:
        print("[stage4] stderr_tail=" + err[-1][:160])
    if not html_path.exists():
        return 4
    if not pdf_path.exists():
        return 5
    print("[stage5] pdf_bytes=%d html_bytes=%d"
          % (pdf_path.stat().st_size, html_path.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
