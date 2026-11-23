---
name: homework-solver-cn
description: 把中文数学作业原件（.md）解析成结构化题目、用 SymPy 确定性求解并走独立通道校验、再排版成可提交的 PDF 答案卷；PDF 生成后强制内容级自检，杜绝“空白 PDF 但退出码为 0”。
version: 1.0.0
author: 2023108610260
---

# 作业自动求解与排版技能（本仓库实现版）

> 本文件已重写为**实际实现**的说明。starter 原版的 `SKILL.md` 描述的是一条 LaTeX / `--compile` 主路径，
> 本机无 `pdflatex/xelatex/lualatex/latexmk/tectonic/pandoc`，该路径已不可用；真实路径是
> **HTML + MathML + 浏览器打印 + pypdf 文本自检**。两者差异见 `docs/2023108610260_C4C_方案设计.md`。

## 何时使用

**适用**：有明确数学表达式的中文作业（线性代数、一阶/二阶 ODE、可直接求值的极限/导数），
要求给出可复算的推导与答案卷。

**不适用**：纯证明题、需要几何作图或开放论证的题目（本流水线不猜答案，一律留白转人工，见“失败语义”）。

## 一条命令

```bash
pip install -r requirements.txt
python homework-solver.py                              # 用仓库自带作业原件，输出到 output/
python homework-solver.py <作业原件.md> <输出目录> [--title "标题"]
python homework-solver.py --selfcheck output/homework.pdf   # 只跑内容门
```

`homework-solver.py` 是**规范入口**（与技能同名），内部委托 `scripts/run_domain.py` 跑完五个阶段，
并在末尾强制走 `pdf_text_check()`；它不承载业务逻辑，只保证"叫得出技能名，就找得到一个能跑的命令"。
`scripts/run_domain.py` 仍然可以直接调用（两者参数与退出码一致）。

真实示例：

```bash
python scripts/run_domain.py problems/2023108610260_C4C_作业原件.md output --title "2023108610260_C4C 作业解答"
```

## 输入 / 输出契约

| 阶段 | 产物 | 关键字段 |
|---|---|---|
| 1 ingest | `1_ingested.json` | `text`、`lines`、分段边界 |
| 2 parse | `2_parsed.json` | `problems[]`：`problem_id`、`problem_text`、`exprs[]` |
| 2.5 manual | 合并 `domain_skills/manual_answers.json` | `applied=N`，人工作答案显式标注来源 |
| 3 solve | `3_solutions.json` | 每题 `steps[]`、`answer`、`meta.verify_ok`、汇总 `total/solved/unsolved/verify_ok/verify_fail` |
| 4 render | `homework.html` | 题干 / 推导步骤 / 最终答案 / 独立校验 四分区，MathML 公式 |
| 5 print | `homework.pdf` | 逐页页码戳记 + `pdf_text_check()` 内容门 |

## 退出码语义（可被 CI 直接判定）

| 码 | 含义 | 触发点 |
|---|---|---|
| `0` | 全链路通过，且 PDF 文本自检合格 | `run_domain.py` 正常结束 |
| `2` | PDF 生成失败（无可用浏览器 / 打印超时 / 输出文件缺失） | stage4 `rc!=0` |
| `7` | **内容门失败**：抽出的正文 < 200 字符或中文字符数为 0 | `pdf_text_check()` |

`7` 是本技能最重要的一条：文件非空、`rc=0`、`ok=True` 都不构成“排版成功”的证据，只有从 PDF 里
抽出足量含中文的正文才算。

## 如何扩展题型（不写正则，扩领域知识）

1. 在 `domain_skills/linear_algebra_ode.yaml` 增加分类规则（题面特征 → 题型键）。
2. 在 `domain_skills/la_ode_templates.json` 增加该题型的求解模板与中文文案
   （`solve_kernel.py` 源码保持纯 ASCII，中文只放该 JSON）。
3. 若需独立校验，在模板里声明 `verify` 方法：矩阵用 `A·A⁻¹=I`，特征值用 `A·v=λ·v`，
   ODE 用回代残差并强制 `.doit()` 后再 `simplify()`（否则未求值导数会让残差恒不为 0）。
4. 跑 `output/3_solutions.json` 的 `verify_fail` 必须为 0，再跑渲染。

## 失败语义（本技能的硬规则）

- **求解失败不编造**：解析不出表达式或模板未覆盖时，该题 `solved=false` 并在答案卷留白说明原因。
- **概念题走人工通道**：写入 `domain_skills/manual_answers.json`，渲染时单独成区并标注“非求解器输出”。
- **校验失败不掩盖**：`verify_ok=false` 的题必须在答案卷保留“校验未通过”标记，不允许只看最终答案像不像。

## 已知边界

- 仅 Windows + Python 3.12.13 实跑；未做 Linux/macOS 验证，未接 CI。
- 无 LLM 对照基线（本机 4 家厂商密钥均未配置），替代为人工逐题手算复核。
- 排版非原生 LaTeX，规范度受浏览器打印能力限制。

## 相关文档

- 方案设计与取舍：`docs/2023108610260_C4C_方案设计.md`
- 逐题结果与 9 个真实缺陷：`docs/2023108610260_C4C_验证报告.md`
- 复盘与改进状态：`docs/2023108610260_C4C_AAR.md`
- 教学场景用法：`docs/2023108610260_C4C_教学说明.md`
- 评分维度对照证据：`docs/2023108610260_C4C_评审对照表.md`
