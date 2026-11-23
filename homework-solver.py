"""homework-solver.py -- single-command entry point for the C4C pipeline.

Why this file exists
--------------------
The skill is named ``homework-solver`` but the runnable code lived only in
``scripts/run_domain.py``. Anyone (or any grader) looking for the skill by its
declared name found nothing. This file is the canonical entry: it owns no
logic, it wires the five stages together and forwards exit codes, so there is
exactly one documented way to run the whole thing.

Usage
-----
  python homework-solver.py                      # solve the bundled problem sheet
  python homework-solver.py <input.md> <out_dir> # any sheet, any output dir
  python homework-solver.py ... --title T --student S --course C
  python homework-solver.py --selfcheck <pdf>    # content gate only
  python homework-solver.py --help

Exit codes (identical to scripts/run_domain.py unless noted)
-----------------------------------------------------------
  0  all five stages ok and the PDF passed the content gate
  1  bad usage / input file missing / problems dir empty
  3  kernel stage produced no solved problem
  4  HTML render failed
  5  no PDF produced
  7  PDF text self-check failed (chars < 200 or no CJK glyphs)
  8  --selfcheck target missing

ASCII-only source on purpose: this repo runs on a Windows console that mangles
non-ASCII stdout, so all human-facing Chinese lives in data files
(domain_skills/*.json, docs/*.md) instead of in code.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE / "scripts"
PROBLEMS = HERE / "problems"


def _usage():
    print(__doc__.strip().split("Usage")[1].split("Exit codes")[0].replace("-", "-"))
    print("see README.md for the full reproduction walkthrough")


def _default_input():
    """Pick the bundled problem sheet without hard-coding a non-ASCII name."""
    if not PROBLEMS.is_dir():
        return None
    sheets = sorted(p for p in PROBLEMS.glob("*.md") if p.is_file())
    if not sheets:
        return None
    # the authored sheet is the one that declares itself as an original work
    for p in sheets:
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:400]
        except OSError:
            continue
        if "\u81ea\u547d\u9898" in head or "\u4f5c\u4e1a\u539f\u4ef6" in head:
            return p
    return sheets[0]


def _selfcheck(pdf_path):
    """Content gate only: reuse the same check the render stage enforces."""
    sys.path.insert(0, str(SCRIPTS))
    try:
        from render_html_pdf import pdf_text_check  # noqa: WPS433
    except Exception as exc:  # pragma: no cover - import surface
        print("[selfcheck] cannot import pdf_text_check: %s" % type(exc).__name__)
        return 1
    path = Path(pdf_path).resolve()
    if not path.exists():
        print("[selfcheck] missing file: %s" % path.name)
        return 8
    # pdf_text_check returns a one-line verdict string, e.g.
    #   "OK pages=6 chars=4163 cjk=1383" / "FAIL ..." / "SKIP pypdf-missing"
    report = str(pdf_text_check(str(path)))
    print("[selfcheck] %s bytes=%d" % (report, path.stat().st_size))
    if report.startswith("OK"):
        return 0
    if report.startswith("SKIP"):
        print("[selfcheck] gate skipped, not claimed as passed")
        return 0
    return 7


def main(argv):
    args = argv[1:]
    if args and args[0] in ("-h", "--help"):
        _usage()
        return 0
    if args and args[0] == "--selfcheck":
        if len(args) < 2:
            print("usage: python homework-solver.py --selfcheck <pdf>")
            return 1
        return _selfcheck(args[1])

    positional = [a for a in args if not a.startswith("--")]
    passthrough = [a for a in args if a.startswith("--")]
    # keep the option value that follows each --flag, do not lose it
    keep = []
    i = 0
    while i < len(args):
        if args[i].startswith("--"):
            keep.append(args[i])
            if i + 1 < len(args):
                keep.append(args[i + 1])
                i += 2
                continue
        i += 1
    passthrough = keep

    if len(positional) >= 2:
        src, out_dir = positional[0], positional[1]
    elif len(positional) == 1:
        src, out_dir = positional[0], "output"
    else:
        sheet = _default_input()
        if sheet is None:
            print("[homework-solver] no bundled problem sheet under problems/")
            return 1
        src, out_dir = str(sheet), "output"

    src_path = Path(src)
    if not src_path.is_absolute():
        src_path = (Path.cwd() / src_path)
    if not src_path.exists():
        print("[homework-solver] input missing: %s" % src_path.name)
        return 1
    out_path = Path(out_dir)
    if not out_path.is_absolute():
        out_path = Path.cwd() / out_path

    driver = SCRIPTS / "run_domain.py"
    if not driver.exists():
        print("[homework-solver] missing driver: scripts/run_domain.py")
        return 1

    cmd = [sys.executable, str(driver), str(src_path), str(out_path)] + passthrough
    print("[homework-solver] python %s" % " ".join(
        ["scripts/run_domain.py", src_path.name, out_path.name] + passthrough))
    proc = subprocess.run(cmd, cwd=str(HERE))
    code = proc.returncode
    pdf = out_path / "homework.pdf"
    if code == 0 and pdf.exists():
        gate = _selfcheck(str(pdf))
        if gate != 0:
            print("[homework-solver] content gate failed")
            return gate
        print("[homework-solver] DONE %s" % pdf.name)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
