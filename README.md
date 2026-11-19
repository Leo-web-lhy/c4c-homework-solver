# 2023108610260_C4C 作业自动求解与排版

C4C 挑战交付仓库：把一份**非微积分极限方向**的作业原件，自动解析、求解、独立校验，并排版成可提交的 PDF 答案卷。

- 挑战 ID：`ch-20260717031447-k82c4m`
- 学号：`2023108610260`
- 公开仓库：https://github.com/Leo-web-lhy/c4c-homework-solver

## 一眼看结果

| 项目 | 结果 |
|---|---|
| 作业原件 | 7 题（6 计算 + 1 概念）· 线性代数 ×3、一阶 ODE ×2、二阶常系数 ODE ×1 |
| 自动求解 | **6 / 7**（概念题如实留白，不编造） |
| 独立校验 | **6 / 6 通过**，`verify_fail = 0` |
| 最终 PDF | [`2023108610260_C4C_output.pdf`](2023108610260_C4C_output.pdf) · 2 页 · 240,718 B · 中文可渲染 |
| 文本级自检 | `[pdf-check] OK pages=2 chars=925 cjk=288` |
| 端到端耗时 | 求解 + 渲染 ≈ 2.2 秒 |

机器可读计数：`output/3_solutions.json` → `{"total":7,"solved":6,"unsolved":1,"verify_ok":6,"verify_fail":0}`。

## 交付物索引

| 文件 | 内容 |
|---|---|
| `2023108610260_C4C_output.pdf` | **最终答案卷（PDF）** |
| `2023108610260_C4C_output.html` | 同一份内容的 HTML 源（MathML 公式） |
| `docs/2023108610260_C4C_方案设计.md` | 方案设计：目标取舍、架构、内核设计、失败处理、与 starter 的关系 |
| `docs/2023108610260_C4C_验证报告.md` | 验证报告：逐题结果 + 人工复核 + 6 个真实缺陷 + 未覆盖边界 |
| `docs/2023108610260_C4C_AI日志.md` | AI 协作日志：按阶段记录任务 / 协作方式 / 产出物 / 人工介入 |
| `docs/2023108610260_C4C_教学说明.md` | 教学说明：这份流水线怎么用在教学与作业批改场景 |
| `problems/2023108610260_C4C_作业原件.md` | 作业原件（自命题，已声明） |
| `output/` | 五阶段中间产物：`1_ingested.json` → `2_parsed.json` → `3_solutions.json` → `homework.html` → `homework.pdf` |

## 复现

```bash
pip install -r requirements.txt
python scripts/run_domain.py problems/2023108610260_C4C_作业原件.md output --title "2023108610260_C4C 作业解答"
```

期望输出：

```
[stage1] chars=608 lines=29
[stage2] problems=7
[stage3] total=7 solved=6 unsolved=1 verify_ok=6 verify_fail=0
[stage4] rc=0
[pdf] ok=True rc=0 2.2s 240718B
[pdf-check] OK pages=2 chars=925 cjk=288
```

退出码：`0` 成功；`2` PDF 生成失败；**`7` PDF 文本自检不通过**（正文 < 200 字符或无中文）。

## 架构

```
作业原件(.md)
   │  ingest       → 1_ingested.json     （正文抽取，608 字符 / 29 行）
   │  parse        → 2_parsed.json       （题号切分 + 数学表达式抽取，7 题）
   │  solve_kernel → 3_solutions.json    （分类 → 求解 → 独立校验）
   │  render       → homework.html       （MathML 排版，去 LaTeX 依赖）
   └  print        → homework.pdf        （Edge headless → pypdf 文本自检）
```

关键设计取舍（详见方案设计）：

1. **先确定性、后生成式**：求解走 SymPy 精确计算，不让模型"写答案"，因此答案可复算、可校验。
2. **校验器与求解器分离**：`A·A⁻¹=I`、`A·v=λ·v`、回代残差、`.doit()+simplify()`；校验计数只认布尔 `meta.verify_ok`，不从中文文案推断。
3. **排版去 LaTeX 依赖**：本机无 `pdflatex/xelatex/tectonic/pandoc`，故用 HTML + MathML + 浏览器打印；中文由系统字体覆盖。
4. **内容门而非存在门**：PDF 生成后必须通过 `pdf_text_check()`，杜绝"空白 PDF 但退出码为 0"。
5. **失败如实留白**：概念题不求解、不编造，标注原因。

## 与 starter 的关系

- **复用**：`scripts/ingest.py`、`scripts/parse_problems.py`、`scripts/bootstrap.py`、`domain_skills/` 的 YAML 结构、`oracles/`、`references/`、`test_cases/` 保留在原处作为参考基线。
- **新增**：`scripts/solve_kernel.py`（约 21.7 KB，纯 ASCII 源码，中文文案外置到 `domain_skills/la_ode_templates.json`）、`scripts/run_domain.py`、`scripts/render_html_pdf.py`、`domain_skills/linear_algebra_ode.yaml`。
- **未使用**：starter 自带的 `test1/test2` 工作单经文本抽取确认为**微积分极限方向**（「切线与 ε‑δ 预备知识」「函数的极限」），与挑战要求冲突，故不作为作业原件。

## 已知边界（不粉饰）

- **无 LLM 对照基线**：本机 4 个厂商密钥均未配置（Moonshot 401 / DashScope 404），挑战建议的"与通用大模型对比"未做，替代为人工手算逐题复核（见验证报告 §2）。
- **仅 Windows + Python 3.12.13 实跑**：未做 Linux/macOS 验证，未接 CI。
- **概念题不做自动求解**：第 7 题留白。

## 环境

- Python 3.12.13；`sympy`、`pyyaml`、`pypdf`、`latex2mathml`
- PDF 打印依赖本机 Edge / Chrome（`find_browser()` 自动探测）
- 不需要 LaTeX 工具链
