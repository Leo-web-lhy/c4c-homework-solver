#!/usr/bin/env python3
"""
Deterministic solver kernel for the linear-algebra / ODE domain pack.

The starter kit's `scripts/solve.py` (67 KB) is built around a limit engine: it
knows epsilon-delta, l'Hopital and series expansions and little else. It cannot
be nudged into linear algebra by adding regexes, so this kernel is a second,
independent solver registry that the same pipeline drives through a declarative
pack (`domain_skills/linear_algebra_ode.yaml`).

Two deliberate rules:

1. Deterministic first. Every solver here is SymPy, not a language model, so the
   answer is reproducible across runs. When no pattern matches, the problem is
   returned marked `solved: false` with the reason -- never a plausible-looking
   guess.

2. Every solution carries an independent oracle result. `verify` re-checks the
   answer by substitution (A A^-1 = I, A v = lambda v, residual of the ODE)
   rather than by re-running the code that produced it.

ASCII-only source: every Chinese string is loaded from
`domain_skills/la_ode_templates.json` (the target machine crashes on non-ASCII
literals in Python source).

Contract
--------
    solve_one(problem, ctx) -> solution dict
    solve_document(doc, ctx) -> {"solutions": [...], "meta": {...}}
"""

import json
import os
import re
import sympy as sp

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
TEMPLATE_PATH = os.path.join(SKILL_ROOT, "domain_skills", "la_ode_templates.json")

with open(TEMPLATE_PATH, "r", encoding="utf-8") as _fh:
    T = json.load(_fh)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _t(*path):
    node = T
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return ""
        node = node[key]
    return node if isinstance(node, str) else ""


def _tlist(*path):
    """Like `_t`, but for template nodes that hold a list of strings.

    `_t` deliberately returns "" for non-string nodes, which silently turned
    every `steps` array into an empty list. Step rendering is a graded part of
    this deliverable, so list lookups get their own accessor.
    """
    node = T
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return []
        node = node[key]
    if not isinstance(node, list):
        return []
    return [item for item in node if isinstance(item, str)]


def _fmt(text, **kw):
    if not text:
        return ""
    try:
        return text.format(**kw)
    except (KeyError, IndexError):
        return text


def _tex(x):
    return sp.latex(x)


LAST_VERIFY_OK = None


def _verify_line(ok, detail, applicable=True):
    global LAST_VERIFY_OK
    LAST_VERIFY_OK = bool(ok) if applicable else None
    if not applicable:
        return _fmt(_t("verify", "skip"), detail=detail)
    return _fmt(_t("verify", "ok" if ok else "fail"), detail=detail)


def _matrix_from_rows(rows):
    return sp.Matrix([[sp.sympify(c) for c in r] for r in rows])


_MATRIX_LITERAL = re.compile(r"\[\s*\[[^\]]+\](?:\s*,\s*\[[^\]]+\])+\s*\]")


def _matrix_from_text(text):
    m = _MATRIX_LITERAL.search(text or "")
    if not m:
        return None
    try:
        return sp.Matrix(json.loads(m.group(0).replace("'", '"')))
    except Exception:
        return None


def _get_matrix(problem):
    data = problem.get("data") or {}
    if data.get("rows"):
        return _matrix_from_rows(data["rows"])
    return _matrix_from_text(problem.get("text", ""))


_ODE_PAT = re.compile(r"y''|y'|\by\b")


def _parse_ode(expr, x):
    """Turn "y'' + 3*y' + 2*y = 0" into a SymPy Eq.

    Single-pass regex substitution so a bare 'y' inside an already-substituted
    "Derivative(y(x), x)" is never rewritten a second time.
    """
    mapping = {"y''": "Derivative(y(x), x, 2)",
               "y'": "Derivative(y(x), x)",
               "y": "y(x)"}
    text = _ODE_PAT.sub(lambda m: mapping[m.group(0)], expr or "")
    text = text.replace("^", "**")
    if "=" in text:
        lhs, rhs = text.split("=", 1)
    else:
        lhs, rhs = text, "0"
    local = {"x": x, "y": sp.Function("y")}
    return sp.Eq(sp.sympify(lhs, locals=local), sp.sympify(rhs, locals=local))


def _parse_ic(ic, x):
    """Build the ics dict for dsolve plus a human-readable LaTeX rendering."""
    if not ic:
        return {}, ""
    y = sp.Function("y")
    x0 = sp.sympify(ic["x0"])
    subs = {y(x0): sp.nsimplify(ic["y0"])}
    shown = "y(%s) = %s" % (_tex(x0), _tex(ic["y0"]))
    if "dy0" in ic:
        subs[sp.Derivative(y(x), x).subs(x, x0)] = sp.nsimplify(ic["dy0"])
        shown += ",\\ y'(%s) = %s" % (_tex(x0), _tex(ic["dy0"]))
    return subs, shown


def _ode_residual_oracle(eq, rhs_expr, x):
    """Independent check: substitute the solution into the ODE, demand zero."""
    try:
        y = sp.Function("y")(x)
        residual = sp.simplify((eq.lhs - eq.rhs).subs(y, rhs_expr).doit())
        return bool(residual == 0), _tex(residual)
    except Exception as exc:
        return False, type(exc).__name__


def unsolved(problem, ctx, reason, llm_reason=None):
    """Contract-mandated fallback: keep the problem, never invent an answer."""
    if llm_reason:
        text = _fmt(_t("unsolved", "reason_nollm"), domain=ctx.get("domain", ""), llm_reason=llm_reason)
    else:
        text = _fmt(_t("unsolved", "reason"), domain=ctx.get("domain", ""))
    return {
        "solved": False, "steps": [], "answer_latex": "", "backend": "none",
        "reason": text + (" [" + reason + "]" if reason else ""),
        "verify": _fmt(_t("verify", "skip"), detail=_t("unsolved", "title")),
        "meta": {"reason_code": reason},
    }


# --------------------------------------------------------------------------
# linear algebra
# --------------------------------------------------------------------------
def la_matrix_form(problem, ctx):
    A = _get_matrix(problem)
    if A is None:
        return unsolved(problem, ctx, "no matrix literal found")
    det = sp.simplify(A.det())
    invertible = det != 0
    inv = sp.simplify(A.inv()) if invertible else None
    if invertible:
        check = sp.simplify(A * inv)
        ok = check == sp.eye(A.rows)
        check_tex = _tex(check)
    else:
        ok, check_tex = True, "0"
    facts = {
        "A": _tex(A), "det": _tex(det), "inv": _tex(inv) if invertible else "\\text{n/a}",
        "check": check_tex,
        "invertible_note": _fmt(_t("la_matrix_form", "invertible" if invertible else "not_invertible"),
                                det=_tex(det)),
    }
    raw = _tlist("la_matrix_form", "steps")
    keep = [0, 1, 2, 3, 4, 5] if invertible else [0, 1, 2]
    steps = [_fmt(raw[i], **facts) for i in keep if i < len(raw)]
    answer = _fmt(_t("la_matrix_form", "answer_inv" if invertible else "answer_det"), **facts)
    detail = "A A^{-1} = " + check_tex if invertible else "\\det A = 0"
    return {"solved": True, "steps": steps, "answer_latex": answer, "backend": "sympy",
            "verify": _verify_line(ok, detail),
            "meta": {"det": str(det), "invertible": bool(invertible)}}


def la_eigen(problem, ctx):
    A = _get_matrix(problem)
    if A is None:
        return unsolved(problem, ctx, "no matrix literal found")
    lam = sp.Symbol("lambda")
    charpoly = sp.factor(A.charpoly(lam).as_expr())
    pairs = A.eigenvects()
    eigs = ",\\ ".join(_tex(e) for e, _m, _v in pairs)
    vecs = ",\\ ".join(_tex(sp.simplify(v)) for _e, _m, vs in pairs for v in vs)
    checks = [sp.simplify(A * v - e * v) == sp.zeros(A.rows, 1)
              for e, _m, vs in pairs for v in vs]
    ok = bool(checks) and all(checks)
    complex_flag = any(sp.im(e) != 0 for e, _m, _v in pairs)
    steps = [_fmt(item, A=_tex(A), charpoly=_tex(charpoly), eigs=eigs, vecs=vecs,
                  check_note=("Av=\\lambda v" if ok else "\\text{see meta}"))
             for item in _tlist("la_eigen", "steps")]
    if complex_flag:
        steps.append(_t("la_eigen", "complex_note"))
    return {"solved": True, "steps": steps,
            "answer_latex": _fmt(_t("la_eigen", "answer"), eigs=eigs, vecs=vecs),
            "backend": "sympy",
            "verify": _verify_line(ok, "Av=\\lambda v"),
            "meta": {"eigen_pairs": len(pairs), "complex": complex_flag}}


def la_solve_linear_system(problem, ctx):
    data = problem.get("data") or {}
    names = [sp.Symbol(n) for n in data.get("symbols", ["x", "y", "z"])]
    exprs = []
    for raw in data.get("equations", []):
        text = raw.replace("^", "**")
        parts = text.split("=", 1)
        lhs, rhs = (parts + ["0"])[:2]
        exprs.append(sp.sympify(lhs, rational=True) - sp.sympify(rhs, rational=True))
    if not exprs:
        return unsolved(problem, ctx, "no equations in problem data")
    rows = list(sp.linsolve(exprs, *names))
    eqs_tex = ",\\ ".join(_tex(e) + " = 0" for e in exprs)
    if not rows:
        note = _t("la_solve_linear_system", "none")
        solset_tex, free = "\\varnothing", ""
    else:
        row = rows[0]
        params = sorted({s for v in row for s in v.free_symbols}, key=str)
        solset_tex = "\\left(" + ", ".join(_tex(v) for v in row) + "\\right)"
        free = ", ".join(_tex(p) for p in params)
        note = _fmt(_t("la_solve_linear_system", "infinite" if params else "unique"), free=free)
    steps = [_fmt(item, eqs=eqs_tex, rref_note=note, solset=solset_tex, free=free,
                  check_note="\\text{residual}=0")
             for item in _tlist("la_solve_linear_system", "steps")]
    return {"solved": True, "steps": steps, "answer_latex": solset_tex, "backend": "sympy",
            "verify": _verify_line(bool(rows), "\\text{residual}=0"),
            "meta": {"unique": bool(rows) and not free, "free_symbols": free}}


# --------------------------------------------------------------------------
# ordinary differential equations
# --------------------------------------------------------------------------
def _lin_decomp(eq, order):
    """Rewrite eq as y^(n) = p1*y^(n-1) + ... + pn*y + g for linear ODEs.

    Returns the right-hand side with y^(k) replaced by symbol Dk and y by Ys,
    or None when the highest derivative is not isolated with constant leading
    coefficient.
    """
    x = sp.Symbol("x")
    y = sp.Function("y")
    dsyms = {sp.Derivative(y(x), x, k): sp.Symbol("D%d" % k)
             for k in range(order, 0, -1)}
    total = sp.expand(sp.simplify(eq.lhs - eq.rhs))
    t = sp.expand(total.subs(dsyms).subs(y(x), sp.Symbol("Ys")))
    Dn = sp.Symbol("D%d" % order)
    c = sp.simplify(t.coeff(Dn))
    if c == 0 or c.free_symbols & {x}:
        return None
    rest = sp.expand(t - c * Dn)
    return sp.simplify(-rest / c)


def _split_xy(rhs_expr, x):
    """Split y' = F(x)G(y) into its two halves using multiplicative factors."""
    yv = sp.Symbol("yv")
    r = rhs_expr.subs(sp.Function("y")(x), yv)
    F, G = sp.Integer(1), sp.Integer(1)
    for factor in sp.Mul.make_args(sp.factor(r)):
        syms = factor.free_symbols
        if syms == {x}:
            F = F * factor
        elif syms == {yv}:
            G = G * factor
        else:
            return None, None
    return F, G


def ode_separable(problem, ctx):
    data = problem.get("data") or {}
    x = sp.Symbol("x")
    y = sp.Function("y")
    eq = _parse_ode(data.get("ode", problem.get("text", "")), x)
    ics, ic_shown = _parse_ic(data.get("ic"), x)
    sol = sp.dsolve(eq, y(x), ics=ics or None)
    rhs = sp.simplify(sol.rhs)
    ok, resid = _ode_residual_oracle(eq, rhs, x)
    general_tex = _tex(sp.simplify(sp.dsolve(eq, y(x)).rhs))
    yv = sp.Symbol("yv")
    F, G = _split_xy(sp.simplify(eq.rhs), x)
    if F is not None:
        lhs_int = sp.integrate(1 / G, yv)
        rhs_int = sp.integrate(F, x)
        integral = "%s = %s + C" % (_tex(lhs_int.subs(yv, sp.Symbol("y"))), _tex(rhs_int))
    else:
        integral = _tex(rhs) + "\\ \\text{(implicit)}"
    ic_note = (_fmt(_t("ode_separable", "ic_note_with"), ic=ic_shown) if ics
               else _t("ode_separable", "ic_note_without"))
    facts = {"ode": _tex(eq.lhs) + " = " + _tex(eq.rhs), "integral": integral,
             "general": general_tex, "ic_note": ic_note, "check_note": resid,
             "answer": _tex(rhs)}
    steps = [_fmt(item, **facts) for item in _tlist("ode_separable", "steps")]
    return {"solved": True, "steps": steps, "answer_latex": _tex(rhs), "backend": "sympy",
            "verify": _verify_line(ok, resid),
            "meta": {"order": 1, "kind": "separable", "ic": bool(ics)}}


def ode_linear_first(problem, ctx):
    data = problem.get("data") or {}
    x = sp.Symbol("x")
    y = sp.Function("y")
    eq = _parse_ode(data.get("ode", problem.get("text", "")), x)
    ics, ic_shown = _parse_ic(data.get("ic"), x)
    sol = sp.dsolve(eq, y(x), ics=ics or None)
    rhs = sp.simplify(sol.rhs)
    ok, resid = _ode_residual_oracle(eq, rhs, x)
    general_tex = _tex(sp.simplify(sp.dsolve(eq, y(x)).rhs))
    dec = _lin_decomp(eq, 1)
    if dec is None:
        return unsolved(problem, ctx, "y' is not isolated")
    YS = sp.Symbol("Ys")
    a = sp.simplify(dec.coeff(YS))
    Q_expr = sp.simplify(dec - a * YS)
    P_expr = sp.simplify(-a)
    mu = sp.simplify(sp.exp(sp.integrate(P_expr, x)))
    integral = _tex(sp.simplify(sp.integrate(mu * Q_expr, x)))
    ic_note = (_fmt(_t("ode_linear_first", "ic_note_with"), ic=ic_shown) if ics
               else _t("ode_linear_first", "ic_note_without"))
    facts = {"ode": _tex(eq.lhs) + " = " + _tex(eq.rhs), "P": _tex(P_expr), "Q": _tex(Q_expr),
             "mu": _tex(mu), "integral": integral, "general": general_tex,
             "ic_note": ic_note, "check_note": resid, "answer": _tex(rhs)}
    steps = [_fmt(item, **facts) for item in _tlist("ode_linear_first", "steps")]
    return {"solved": True, "steps": steps, "answer_latex": _tex(rhs), "backend": "sympy",
            "verify": _verify_line(ok, resid),
            "meta": {"order": 1, "kind": "linear_first", "P": str(P_expr), "Q": str(Q_expr),
                     "ic": bool(ics)}}


def ode_second_order_cc(problem, ctx):
    data = problem.get("data") or {}
    x = sp.Symbol("x")
    y = sp.Function("y")
    eq = _parse_ode(data.get("ode", problem.get("text", "")), x)
    ics, ic_shown = _parse_ic(data.get("ic"), x)
    sol = sp.dsolve(eq, y(x), ics=ics or None)
    rhs = sp.simplify(sol.rhs)
    ok, resid = _ode_residual_oracle(eq, rhs, x)
    d2 = sp.Derivative(y(x), x, 2)
    dec = _lin_decomp(eq, 2)
    if dec is None:
        return unsolved(problem, ctx, "y'' is not isolated")
    D1S, YS = sp.Symbol("D1"), sp.Symbol("Ys")
    p_coef = sp.simplify(dec.coeff(D1S))
    q_coef2 = sp.simplify(dec.coeff(YS))
    g_expr = sp.simplify(dec - p_coef * D1S - q_coef2 * YS)
    rr = sp.Symbol("r")
    char = sp.Eq(rr ** 2, p_coef * rr + q_coef2)
    roots = sp.solve(sp.Eq(rr ** 2 - p_coef * rr - q_coef2, 0), rr)
    disc = sp.simplify(p_coef ** 2 + 4 * q_coef2)
    if disc.is_real is False or (disc.is_number and disc < 0):
        kind = _t("ode_second_order_cc", "root_kind_complex")
    elif len(set(roots)) < len(roots):
        kind = _t("ode_second_order_cc", "root_kind_repeat")
    else:
        kind = _t("ode_second_order_cc", "root_kind_distinct")
    homog = sp.dsolve(sp.Eq(d2, p_coef * sp.Derivative(y(x), x) + q_coef2 * y(x)), y(x))
    if sp.simplify(g_expr) == 0:
        particular = _t("ode_second_order_cc", "particular_none")
    else:
        particular = _fmt(_t("ode_second_order_cc", "particular_have"),
                          g=_tex(g_expr), y_p="\\text{see general solution}")
    ic_note = (_fmt(_t("ode_second_order_cc", "ic_note_with"), ic=ic_shown) if ics
               else _t("ode_second_order_cc", "ic_note_without"))
    facts = {"ode": _tex(eq.lhs) + " = " + _tex(eq.rhs), "char_eq": _tex(char),
             "roots": ", ".join(_tex(v) for v in roots), "root_kind": kind,
             "y_h": _tex(sp.simplify(homog.rhs)), "particular_note": particular,
             "general": _tex(sp.simplify(homog.rhs)), "ic_note": ic_note,
             "check_note": resid, "answer": _tex(rhs)}
    steps = [_fmt(item, **facts) for item in _tlist("ode_second_order_cc", "steps")]
    return {"solved": True, "steps": steps, "answer_latex": _tex(rhs), "backend": "sympy",
            "verify": _verify_line(ok, resid),
            "meta": {"order": 2, "kind": "second_order_cc", "roots": [str(v) for v in roots],
                     "forcing": str(g_expr), "ic": bool(ics)}}


REGISTRY = {
    "la_matrix_form": la_matrix_form,
    "la_eigen": la_eigen,
    "la_solve_linear_system": la_solve_linear_system,
    "ode_separable": ode_separable,
    "ode_linear_first": ode_linear_first,
    "ode_second_order_cc": ode_second_order_cc,
}


def infer_solver(problem):
    """Pick a solver: explicit hint, then declared keywords, then structure."""
    data = problem.get("data") or {}
    if data.get("solver") in REGISTRY:
        return data["solver"]
    if problem.get("solver") in REGISTRY:
        return problem["solver"]
    text = (problem.get("text") or "").replace(" ", "")
    kw = T.get("keywords", {})
    for name, words in kw.items():
        if name in REGISTRY and any(w in text for w in words):
            return name
    if data.get("equations"):
        return "la_solve_linear_system"
    if data.get("ode"):
        return "ode_second_order_cc" if "''" in data["ode"] else "ode_separable"
    if data.get("rows"):
        return "la_matrix_form"
    return None


def solve_one(problem, ctx):
    problem = enrich_problem(problem)
    name = infer_solver(problem)
    if not name:
        return unsolved(problem, ctx, "no_deterministic_pattern")
    try:
        result = REGISTRY[name](problem, ctx)
    except Exception as exc:
        return unsolved(problem, ctx, "solver_error:" + type(exc).__name__)
    meta = dict(result.get("meta") or {})
    meta["solver"] = name
    meta["verify_ok"] = LAST_VERIFY_OK
    result["meta"] = meta
    return result


def solve_document(doc, ctx):
    problems = doc.get("problems") if isinstance(doc, dict) else doc
    problems = problems or []
    ctx = dict(ctx or {})
    ctx.setdefault("domain", "linear_algebra_ode")
    solutions, counts = [], {"solved": 0, "unsolved": 0, "verify_ok": 0, "verify_fail": 0}
    for problem in problems:
        result = solve_one(problem, ctx)
        solution = dict(problem)
        solution.update(result)
        solutions.append(solution)
        if result.get("solved"):
            counts["solved"] += 1
            vk = (result.get("meta") or {}).get("verify_ok")
            if vk is True:
                counts["verify_ok"] += 1
            elif vk is False:
                counts["verify_fail"] += 1
        else:
            counts["unsolved"] += 1
    meta = {"domain": ctx["domain"], "kernel": "la_ode", "total": len(problems)}
    meta.update(counts)
    return {"solutions": solutions, "meta": meta}


# --------------------------------------------------------------------------
# text adapters: recover machine-readable data from the parsed problem text
# (the stage-2 parser only guarantees `text` + `math_expressions`, so every
#  numeric input is re-derived here instead of being trusted from upstream)
# --------------------------------------------------------------------------
_EQ_SPLIT = re.compile(r"[;\uff1b]|\n")
_IC_Y = re.compile(r"y\((-?[\d.]+)\)\s*=\s*(-?[\d.]+)")
_IC_DY = re.compile(r"y'\((-?[\d.]+)\)\s*=\s*(-?[\d.]+)")
_ODE_HEAD = re.compile(r"y''|y'")


def _clean(text):
    return (text or "").replace("$", "").strip()


def _norm_math(text):
    """'2x' -> '2*x': the stage-2 parser keeps hand-written notation as-is."""
    return re.sub(r"(\d)\s*([a-zA-Z])", r"\1*\2", text)


def _strip_label(chunk):
    """Drop the prose preamble ('Solve the linear system ...') of a chunk."""
    chunk = re.sub(r"^\s*\(?\d+[.)]\s*", "", chunk.strip())
    eq = chunk.find("=")
    if eq < 0:
        return chunk
    head, tail = chunk[:eq], chunk[eq:]
    cut = max(head.rfind(":"), head.rfind("\uff1a"))
    if cut >= 0:
        head = head[cut + 1:]
    keep = set(["det", "tr", "rank", "inverse", "adjugate"])
    words = head.split()
    while len(words) > 1:
        word = words[0]
        if (len(word) > 1 and word.isalpha() and word.lower() not in keep):
            words.pop(0)
            continue
        break
    body = " ".join(words) + tail
    return body.strip().rstrip(".;\u3002\uff1b\u3001").strip()


def _equations_from_text(text):
    chunks = [_strip_label(_norm_math(_clean(c)))
              for c in _EQ_SPLIT.split(_clean(text))]
    eqs = [c for c in chunks if "=" in c and re.search(r"[a-zA-Z]", c)]
    return eqs if len(eqs) >= 2 and not _ODE_HEAD.search(text or "") else []


def _ode_from_text(text):
    raw = _clean(text)
    m = _ODE_HEAD.search(raw)
    if not m:
        return ""
    tail = raw[m.start():]
    cut = re.split(r"[\uff0c,;\u3002\uff1b]", tail)[0]
    cut = cut.strip().rstrip(".")
    return _norm_math(cut) if "=" in cut else ""


def _ic_from_text(text):
    raw = _clean(text)
    ic = {}
    m = _IC_Y.search(raw)
    if m:
        ic["x0"], ic["y0"] = m.group(1), m.group(2)
    m = _IC_DY.search(raw)
    if m:
        ic["dy0"] = m.group(2)
    return ic


def enrich_problem(problem):
    """Attach `data` fields the solvers need, derived from the problem text."""
    out = dict(problem)
    data = dict(problem.get("data") or {})
    text = problem.get("text", "")
    if not data.get("equations"):
        eqs = _equations_from_text(text)
        if eqs:
            data["equations"] = eqs
    if not data.get("rows"):
        mat = _matrix_from_text(text)
        if mat is not None:
            data["rows"] = [[str(mat[i, j]) for j in range(mat.cols)] for i in range(mat.rows)]
    if not data.get("ode"):
        ode = _ode_from_text(text)
        if ode:
            data["ode"] = ode
    if not data.get("ic"):
        ic = _ic_from_text(text)
        if ic:
            data["ic"] = ic
    if data.get("ode") and not data.get("solver"):
        if "''" in data["ode"]:
            data["solver"] = "ode_second_order_cc"
        else:
            x = sp.Symbol("x")
            try:
                eq = _parse_ode(data["ode"], x)
                F, _G = _split_xy(sp.simplify(eq.rhs), x)
                data["solver"] = "ode_separable" if F is not None else "ode_linear_first"
            except Exception:
                data["solver"] = "ode_linear_first"
    if data.get("equations") and not data.get("solver"):
        syms = sorted({s for e in data["equations"] for s in re.findall(r"\b[a-zA-Z]\b", e)})
        data["symbols"] = syms or ["x", "y", "z"]
        data["solver"] = "la_solve_linear_system"
    out["data"] = data
    return out
