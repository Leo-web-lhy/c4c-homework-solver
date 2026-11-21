#!/usr/bin/env python3
"""
Stage 4b: HTML + MathML PDF backend (LaTeX-free).

Why this module exists
----------------------
The starter kit's Stage 5 shelled out to pdflatex/xelatex. On a machine with no
TeX distribution installed, Stage 5 silently degraded to "tex only, no PDF".
This backend removes that hard dependency for the common case:

    LaTeX math  --latex2mathml-->  MathML  --Edge/Chrome headless-->  real PDF

Chromium 109+ ships MathML Core, so a browser that is already present on almost
every Windows/macOS desktop can act as the typesetting engine. No TeX, no
network, no LaTeX package downloads.

Honest limits (measured, not assumed):
  * MathML Core is not TeX. amsmath constructs such as align/aligned,
    tcolorbox, and custom macros are not supported; latex2mathml raises and we
    fall back to a preformatted plain-text rendering instead of failing the run.
  * Output is vector text (selectable), not a bitmap: verified by pypdf text
    extraction on the generated PDF.
  * If neither Edge nor Chrome exists, html_to_pdf() returns False and the
    caller keeps the .tex + .html artifacts. The pipeline never pretends a PDF
    was produced.

Usage:
    python render_html_pdf.py solutions.json out.html out.pdf [--title T]

Only ASCII source is kept in this file on purpose: the target machine crashes
on non-ASCII literals inside Python/CJK console output (0xC0000005). All Chinese
UI strings are written as \\uXXXX escapes and all data comes from JSON.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from html import escape

try:
    import latex2mathml.converter as _l2m
except Exception:  # pragma: no cover - dependency missing
    _l2m = None

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/microsoft-edge",
    "/usr/bin/google-chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]

_MATHML_CACHE = {}
MATH_FAIL = []


def tex_to_mathml(tex, display="inline"):
    key = (tex.strip(), display)
    if key in _MATHML_CACHE:
        return _MATHML_CACHE[key]
    if _l2m is None:
        MATH_FAIL.append((tex, "latex2mathml not installed"))
        return "<code>" + escape(tex) + "</code>"
    try:
        out = _l2m.convert(tex.strip())
        if display == "block":
            out = out.replace("<math", '<math display="block"', 1)
        _MATHML_CACHE[key] = out
        return out
    except Exception as exc:
        MATH_FAIL.append((tex.strip()[:120], type(exc).__name__))
        return "<code>" + escape(tex) + "</code>"


_MATH_SPLIT = re.compile(r"(\$\$.+?\$\$|\$[^$]+?\$)", re.S)


def rich(text):
    """Render a mixed Chinese/prose + inline-math string into HTML."""
    pieces = _MATH_SPLIT.split(text or "")
    out = []
    for idx, piece in enumerate(pieces):
        if not piece:
            continue
        if idx % 2 == 1:
            if piece.startswith("$$"):
                out.append('<span class="dispmath">' + tex_to_mathml(piece[2:-2], "block") + "</span>")
            else:
                out.append(tex_to_mathml(piece[1:-1], "inline"))
        else:
            out.append(_markdown_inline(piece))
    return "".join(out)


_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _markdown_inline(text):
    t = escape(text)
    t = _BOLD.sub(r"<strong>\1</strong>", t)
    t = t.replace("`", "")
    return t.replace("\n", "<br>")


CSS = """
@page { size: A4; margin: 17mm 15mm 16mm 15mm; }
* { box-sizing: border-box; }
body { font-family: "Microsoft YaHei","Noto Sans SC","SimSun",serif; font-size: 10.6pt;
       line-height: 1.62; color: #1a1a1a; margin: 0; }
h1 { font-size: 17pt; text-align: center; margin: 0 0 3pt 0; letter-spacing: .5pt; }
.sub { text-align: center; font-size: 10pt; color: #444; margin: 0; }
.meta { text-align: center; font-size: 9.2pt; color: #666; margin: 3pt 0 12pt 0; }
hr.rule { border: 0; border-top: 1.4pt solid #1d4e89; margin: 8pt 0 12pt 0; }
h2 { font-size: 12pt; color: #1d4e89; margin: 15pt 0 5pt 0; padding-bottom: 2pt;
     border-bottom: .7pt solid #c9d8ea; page-break-after: avoid; }
h3 { font-size: 10.8pt; margin: 10pt 0 3pt 0; color: #223; }
.q { margin: 2pt 0 5pt 0; }
.step { margin: 1.5pt 0 1.5pt 12pt; color: #2b2b2b; }
.note { margin: 2pt 0 2pt 12pt; color: #666; font-size: 9.4pt; }
.dispmath { display: block; text-align: center; margin: 5pt 0 5pt 0; overflow-x: auto; }
math { font-size: 10.8pt; }
.ans { border-left: 3pt solid #2a9d6e; background: #f2fbf6; padding: 4pt 8pt;
       margin: 6pt 0 4pt 0; }
.ans .lbl { font-weight: bold; color: #1d7a55; }
.unsolved { border-left: 3pt solid #c0392b; background: #fdf3f2; padding: 4pt 8pt;
            margin: 6pt 0 4pt 0; color: #96271b; }
.tag { display: inline-block; font-size: 8.6pt; color: #fff; background: #1d4e89;
       border-radius: 2pt; padding: .5pt 4pt; margin-left: 5pt; vertical-align: 1.5pt; }
.tag.new { background: #b06f00; }
table.sum { border-collapse: collapse; width: 100%; font-size: 9.4pt; margin: 8pt 0; }
table.sum th, table.sum td { border: .6pt solid #bbb; padding: 3pt 6pt; text-align: left; }
table.sum th { background: #eef3fa; }
.ok { color: #1d7a55; font-weight: bold; }
.bad { color: #b03a2e; font-weight: bold; }
footer { margin-top: 14pt; padding-top: 5pt; border-top: .6pt solid #ccc;
         font-size: 8.6pt; color: #777; }
.prob { page-break-inside: avoid; margin: 0 0 6pt 0; }
ol.steps { margin: 3pt 0 4pt 0; padding-left: 20pt; }
ol.steps li { margin: 2.5pt 0; line-height: 1.6; }
.seclbl { display: block; font-size: 8.4pt; font-weight: bold; color: #1d4e89;
          letter-spacing: .3pt; margin: 6pt 0 1pt 0; text-transform: none; }
.vr { border-left: 3pt solid #1d4e89; background: #f5f8fc; padding: 3pt 8pt;
      margin: 4pt 0 2pt 0; font-size: 9.4pt; color: #26456b; }
.vr .lbl { font-weight: bold; }
.vr.bad { border-left-color: #b03a2e; background: #fdf3f2; color: #96271b; }
.manual { border: .8pt dashed #b06f00; background: #fffdf5; padding: 6pt 9pt;
          margin: 6pt 0 2pt 0; }
.manual .mlbl { font-weight: bold; color: #8a5600; font-size: 9.6pt; margin-bottom: 3pt; }
.manual p.mp { margin: 3pt 0; text-align: justify; line-height: 1.68; }
.manual p.mnote { margin: 5pt 0 0 0; padding-top: 4pt; border-top: .5pt dotted #d8b878;
                  color: #5c3d00; }
"""


def build_html(solutions, meta):
    title = meta.get("title", "Homework Solutions")
    course = meta.get("course", "")
    student = meta.get("student", "")
    date_str = meta.get("date", "")
    sets = meta.get("sets", [])
    if not sets and solutions:
        sets = [{"heading": meta.get("section_title", "\u9898\u76ee\u4e0e\u89e3\u7b54"),
                 "items": solutions}]
    doc_no = meta.get("doc", "")

    parts = ['<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">',
             "<title>" + escape(title) + "</title><style>" + CSS + "</style></head><body>"]
    parts.append("<h1>" + escape(title) + "</h1>")
    if course:
        parts.append('<p class="sub">' + escape(course) + "</p>")
    parts.append('<p class="meta">' + escape(student) + " &middot; " + escape(date_str)
                 + (" &middot; " + escape(doc_no) if doc_no else "") + "</p>")
    parts.append('<hr class="rule">')

    for group in sets:
        parts.append("<h2>" + escape(group.get("heading", "")) + "</h2>")
        if group.get("intro"):
            parts.append('<p class="note">' + rich(group["intro"]) + "</p>")
        for sol in group.get("items", []):
            parts.append(render_problem(sol))

    stats = meta.get("stats")
    if stats:
        parts.append('<h2>' + escape(stats.get("heading", "Summary")) + "</h2>")
        parts.append('<table class="sum"><tr>')
        for col in stats.get("columns", []):
            parts.append("<th>" + escape(col) + "</th>")
        parts.append("</tr>")
        for row in stats.get("rows", []):
            parts.append("<tr>")
            for cell in row:
                parts.append("<td>" + cell + "</td>")
            parts.append("</tr>")
        parts.append("</table>")

    parts.append("<footer>" + rich(meta.get("footer", "")) + "</footer>")
    parts.append("</body></html>")
    return "\n".join(parts)


_L_Q = "\u9898\u5e72"
_L_STEP = "\u63a8\u5bfc\u6b65\u9aa4"
_L_ANS = "\u6700\u7ec8\u7b54\u6848"
_L_VERIFY = "\u72ec\u7acb\u6821\u9a8c"
_L_MANUAL = "\u4eba\u5de5\u8865\u5145\u8bf4\u660e\uff08\u4f5c\u8005\u64b0\u5199\uff0c\u975e\u6c42\u89e3\u5668\u8f93\u51fa\uff09"
_L_UNSOLVED = "\u672a\u81ea\u52a8\u6c42\u89e3"


def render_problem(sol):
    pid = escape(str(sol.get("problem_id", sol.get("id", "")) or ""))
    out = ['<div class="prob">', "<h3>"]
    out.append(pid + ". ")
    out.append(rich(sol.get("title", "")))
    if sol.get("tag"):
        cls = "tag new" if sol.get("tag_new") else "tag"
        out.append('<span class="' + cls + '">' + escape(sol["tag"]) + "</span>")
    out.append("</h3>")
    _ptext = sol.get("problem_text") or sol.get("text") or ""
    if _ptext:
        out.append('<div class="seclbl">' + _L_Q + "</div>")
        out.append('<div class="q">' + rich(_ptext) + "</div>")
    if sol.get("solved"):
        _steps = [s for s in (sol.get("steps") or []) if str(s).strip()]
        if _steps:
            out.append('<div class="seclbl">' + _L_STEP + "</div>")
            out.append('<ol class="steps">')
            for step in _steps:
                out.append("<li>" + rich(str(step)) + "</li>")
            out.append("</ol>")
        if sol.get("answer_latex"):
            out.append('<div class="ans"><span class="lbl">' + _L_ANS
                       + "\uff1a</span> " + rich(_as_math(sol["answer_latex"])) + "</div>")
    else:
        out.append('<div class="unsolved"><strong>' + _L_UNSOLVED
                   + "\uff1a</strong> " + rich(sol.get("reason", "")) + "</div>")
    _ma = sol.get("manual_answer")
    if isinstance(_ma, dict):
        _paras = [p for p in (_ma.get("paragraphs") or []) if str(p).strip()]
        out.append('<div class="manual">')
        out.append('<div class="mlbl">' + escape(_ma.get("label") or _L_MANUAL) + "</div>")
        for _p in _paras:
            out.append('<p class="mp">' + rich(str(_p)) + "</p>")
        if _ma.get("note"):
            out.append('<p class="mnote">' + rich(str(_ma["note"])) + "</p>")
        out.append("</div>")
    for sub in sol.get("sub_solutions", []):
        out.append(render_problem(sub))
    if sol.get("verify"):
        _ok = bool((sol.get("meta") or {}).get("verify_ok"))
        out.append('<div class="vr' + ("" if _ok else " bad") + '"><span class="lbl">'
                   + _L_VERIFY + "\uff1a</span> " + rich(sol["verify"]) + "</div>")
    out.append("</div>")
    return "\n".join(out)


def _as_math(tex):
    """Wrap bare LaTeX into $$...$$ so rich() routes it through MathML."""
    t = (tex or "").strip()
    if not t:
        return ""
    if t.startswith("$") or "\\(" in t:
        return t
    return "$$" + t + "$$"


def find_browser():
    for path in BROWSERS:
        if os.path.exists(path):
            return path
    return None


def html_to_pdf(html_path, pdf_path, timeout=240):
    browser = find_browser()
    if not browser:
        return False, "no Edge/Chrome found"
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
    profile = os.path.join(tempfile.gettempdir(), "c4c_pdf_profile")
    cmd = [browser, "--headless=new", "--disable-gpu", "--no-first-run",
           "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
           "--virtual-time-budget=8000",
           "--user-data-dir=" + profile,
           "--print-to-pdf=" + pdf_path,
           "file:///" + os.path.abspath(html_path).replace("\\", "/")]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "browser timeout after %ds" % timeout
    dt = round(time.time() - t0, 1)
    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1000:
        return True, "rc=%s %ss %sB" % (proc.returncode, dt, os.path.getsize(pdf_path))
    err = (proc.stderr or b"").decode("utf-8", "replace")[:300]
    return False, "rc=%s %ss; stderr=%s" % (proc.returncode, dt, err)


def pdf_text_check(pdf_path, min_chars=200):
    """A produced PDF is only accepted when it carries real text.

    Regression guard: a payload without 'sets' once rendered an empty body and
    still returned rc=0 with a 15.9 KB PDF (1 page, 20 chars, 0 CJK). File
    existence plus size is therefore not sufficient evidence.
    """
    try:
        import pypdf
    except Exception:
        return "SKIP pypdf-missing"
    try:
        rd = pypdf.PdfReader(pdf_path)
        txt = "".join((p.extract_text() or "") for p in rd.pages)
    except Exception as exc:
        return "SKIP %s" % type(exc).__name__
    cjk = sum(1 for ch in txt if "\u4e00" <= ch <= "\u9fff")
    verdict = "FAIL" if (len(txt) < min_chars or cjk == 0) else "OK"
    return "%s pages=%d chars=%d cjk=%d" % (verdict, len(rd.pages), len(txt), cjk)


def _page_stamp(pdf_path, meta):
    """Overlay a real page footer ("page i / n") onto the printed PDF.

    Chromium's CLI cannot set a custom print footer template, and Chrome does
    not support @page margin boxes, so the numbers come from a second one-page-
    per-sheet overlay PDF merged with pypdf. Returns an ASCII status line.
    """
    try:
        import pypdf
    except Exception:
        return "SKIP pypdf-missing"
    try:
        rd = pypdf.PdfReader(pdf_path)
        n = len(rd.pages)
    except Exception as exc:
        return "SKIP %s" % type(exc).__name__
    if n < 1:
        return "SKIP no pages"
    right = str(meta.get("stamp_right") or "")
    sheets = []
    for i in range(n):
        sheets.append('<div class="pg"><div class="ft">' + str(i + 1) + " / " + str(n)
                      + ((" &middot; " + escape(right)) if right else "") + "</div></div>")
    html = ('<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><style>'
            "@page{size:A4;margin:0}"
            "*{box-sizing:border-box}"
            'body{margin:0;font-family:"Microsoft YaHei","SimSun",serif;font-size:8.2pt;color:#777}'
            ".pg{width:210mm;height:296.9mm;position:relative;page-break-after:always}"
            ".ft{position:absolute;left:15mm;right:15mm;bottom:9mm;padding-top:2.5mm;"
            "border-top:.5pt solid #d5d5d5;text-align:center}"
            "</style></head><body>" + "".join(sheets) + "</body></html>")
    tmp_html = os.path.join(tempfile.gettempdir(), "c4c_page_stamp.html")
    tmp_pdf = os.path.join(tempfile.gettempdir(), "c4c_page_stamp.pdf")
    try:
        with open(tmp_html, "w", encoding="utf-8") as fh:
            fh.write(html)
    except Exception as exc:
        return "SKIP write-%s" % type(exc).__name__
    _ok, _info = html_to_pdf(tmp_html, tmp_pdf)
    if not _ok:
        return "SKIP stamp-render(%s)" % _info[:60]
    try:
        ov = pypdf.PdfReader(tmp_pdf)
        wr = pypdf.PdfWriter(clone_from=pdf_path)
        stamped = 0
        for i, page in enumerate(wr.pages):
            if i < len(ov.pages):
                page.merge_translated_page(ov.pages[i], 0, 0)
                stamped += 1
        with open(pdf_path, "wb") as fh:
            wr.write(fh)
    except Exception as exc:
        return "SKIP merge-%s" % type(exc).__name__
    return "OK stamped=%d" % stamped


def main(argv):
    if len(argv) < 4:
        print("usage: python render_html_pdf.py <solutions.json> <out.html> <out.pdf> [--title T] [--student S] [--course C]")
        return 1
    with open(argv[1], "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if isinstance(payload, list):
        payload = {"solutions": payload, "meta": {}}
    meta = payload.get("meta", {})
    _argv = argv[4:]
    _i = 0
    while _i < len(_argv):
        if _argv[_i] == "--title" and _i + 1 < len(_argv):
            meta["title"] = _argv[_i + 1]; _i += 2; continue
        if _argv[_i] == "--student" and _i + 1 < len(_argv):
            meta["student"] = _argv[_i + 1]; _i += 2; continue
        if _argv[_i] == "--course" and _i + 1 < len(_argv):
            meta["course"] = _argv[_i + 1]; _i += 2; continue
        _i += 1
    if not meta.get("student"):
        meta["student"] = "2023108610260"
    if not meta.get("course"):
        meta["course"] = ("\u7ebf\u6027\u4ee3\u6570\u4e0e\u5e38\u5fae\u5206\u65b9\u7a0b")
    if not meta.get("title"):
        meta["title"] = ("\u4f5c\u4e1a\u89e3\u7b54")
    _tot = len(payload["solutions"])
    _sol = sum(1 for s in payload["solutions"] if s.get("solved"))
    _vok = sum(1 for s in payload["solutions"] if (s.get("meta") or {}).get("verify_ok"))
    meta["footer"] = ("\u5171 %d \u9898\uff1b\u81ea\u52a8\u6c42\u89e3 %d \u9898\uff1b\u72ec\u7acb\u6821\u9a8c\u901a\u8fc7 %d \u9898\uff1b\u672a\u81ea\u52a8\u6c42\u89e3 %d \u9898\uff08\u5b9e\u5982\u7559\u767d\uff09" % (_tot, _sol, _vok, _tot - _sol))
    html = build_html(payload["solutions"], meta)
    with open(argv[2], "w", encoding="utf-8") as fh:
        fh.write(html)
    print("[html] %s (%d chars)" % (argv[2], len(html)))
    ok, info = html_to_pdf(argv[2], argv[3])
    print("[pdf] ok=%s %s" % (ok, info))
    if ok:
        meta["stamp_right"] = (str(meta.get("student") or "") + " \u00b7 C4C").strip(" \u00b7")
        print("[pdf-pages] %s" % _page_stamp(argv[3], meta))
        _chk = pdf_text_check(argv[3])
        print("[pdf-check] %s" % _chk)
        if _chk.startswith("FAIL"):
            if MATH_FAIL:
                print("[math-fallback] %d expression(s) degraded to plain text" % len(MATH_FAIL))
            return 7
    if MATH_FAIL:
        print("[math-fallback] %d expression(s) degraded to plain text" % len(MATH_FAIL))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
