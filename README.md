# Auto-Debug Agent

Auto-Debug Agent 是一个面向 Python 运行时错误的自动调试项目。系统将一次调试任务拆分为四个阶段：复现错误、分析根因、生成补丁和验证结果，并通过结构化协议在阶段之间传递上下文。

项目包含手写 orchestrator、LangGraph 对照实现，以及一套用于批量评估修复效果的 evals 框架。运行过程中的阶段消息、沙箱补丁、验证结果和评估产物都会被持久化，便于审计和复盘。

## 流水线

```text
[debug sample_bugs/bug1.py]
        │
        ▼
┌────────────────┐      error_info       ┌────────────────┐
│   Reproducer   │ ────────────────────▶ │    Analyst     │
│   运行文件      │                       │    定位根因     │
└────────────────┘                       └────────┬───────┘
                                                   │
                                                   │ root_cause + issues
                                                   ▼
┌────────────────┐      test_result      ┌────────────────┐
│    Verifier    │ ◀──────────────────── │     Fixer      │
│    验证补丁     │                       │    生成补丁     │
└────────────────┘                       └────────────────┘
```

阶段之间通过 `TeamProtocol` dataclass 传递状态，并写入 `.debug/bus/`。Verifier 基于 patched file 的运行结果、`[exit_code=N]` 和 traceback 检查生成结构化 JSON verdict，避免依赖简单字符串匹配判断 PASS/FAIL。

## 项目结构

```text
auto-debug-agent/
├── main.py                    # CLI 入口和手写 orchestrator
├── requirements.txt           # 基础依赖
├── autodebug/
│   ├── config.py              # 模型、路径和运行参数
│   ├── protocol.py            # TeamProtocol 和消息总线
│   ├── pipeline.py            # run_subagent() 与四阶段 Agent
│   ├── tools.py               # 工具实现和 tool schema
│   ├── sandbox.py             # 沙箱副本和写回逻辑
│   ├── memory.py              # 跨会话 error -> fix 记忆
│   ├── skills.py              # 按需加载 skills/
│   ├── tasks.py               # 阶段任务看板
│   └── ui.py                  # 终端摘要和权限确认
├── skills/
│   ├── log-parser/
│   ├── static-analysis/
│   └── fixer/
├── sample_bugs/               # 10 个内置多 bug 示例
├── evals/                     # 批量评估和评估结果分析
└── langgraph_version/         # LangGraph 对照版本
```

运行时会生成 `.debug/`，用于保存消息总线、沙箱副本、记忆、上下文压缩前的 transcript 和任务状态。该目录属于运行产物，不是源码的一部分。

## 快速开始

安装依赖：

```bash
cd auto-debug-agent
pip install -r requirements.txt
```

配置模型环境变量。`MODEL_ID` 必填；`ANTHROPIC_BASE_URL` 可选，用于 Anthropic-compatible API：

```bash
export MODEL_ID=MiniMax-M2.5
export ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic
```

也可以将变量写入 `.env`，项目会通过 `python-dotenv` 自动加载。

启动 CLI：

```bash
python main.py
```

运行调试任务：

```text
debug >> debug sample_bugs/bug1.py
```

## CLI 命令

| 命令 | 说明 |
| --- | --- |
| `debug <file>` | 对指定 Python 文件运行完整四阶段调试流水线 |
| `memory` | 查看最近 10 条历史修复记忆 |
| `tasks` | 查看当前阶段任务看板 |
| `/history` | 查看最近 5 条消息总线记录 |
| `help` | 显示帮助 |
| `q` / `exit` | 退出 CLI |

Fixer 只修改 `.debug/sandbox/` 中的文件副本。补丁通过验证后，CLI 会询问是否将沙箱中的修复复制回原文件；如果不确认写回，原文件保持不变。

## 运行时产物

```text
.debug/
├── bus/             # 每个阶段的 TeamProtocol JSON 记录
├── eval_work/       # evals 使用的临时工作副本
├── memory/          # 成功修复后的 error -> fix 记忆
├── sandbox/         # Fixer 修改的文件副本
├── transcripts/     # 上下文压缩前的完整对话存档
└── tasks.json       # reproduce/analyse/fix/verify 状态
```

这些文件用于调试、审计和跨会话复用，不需要手动创建。

## 关键实现

- `run_subagent()` 为每个阶段创建独立消息历史，并处理工具调用、API 重试、`max_tokens` 续写和上下文压缩。
- `TeamProtocol.issues` 使用轻量字典记录异常类型、位置、摘要、状态和发现轮次，用于追踪多问题修复过程。
- `run_bash()` 在输出末尾附加 `[exit_code=N]`，Verifier 使用退出码和 traceback 共同判断补丁是否通过。
- `sandbox_diff` 使用 unified diff 比较原文件和沙箱副本，使 Verifier 能审查实际补丁内容。
- `autodebug/ui.py` 复用终端摘要、Markdown 清理和权限确认逻辑，供手写 orchestrator 和 LangGraph 版本共同使用。
- `skills/` 采用按需加载机制：system prompt 只提供技能描述，Agent 需要时通过 `load_skill()` 读取完整 `SKILL.md`。

## Evals 评估

`evals/` 用于批量评估 Auto-Debug Agent 的修复效果。评估脚本会将 `sample_bugs/` 中的样例复制到临时目录，使用 `auto_approve=True` 调用主流水线，并通过 checker 计算得分。原始样例文件不会被修改。

```text
sample_bugs/bug1.py
        │
        │ 复制到临时目录
        ▼
run_debug_pipeline(auto_approve=True)
        │
        ├── 评分：运行正确性、bug 覆盖率、补丁大小、执行效率
        │
        └── 产物：results.json + cases/*.json
```

运行评估：

```bash
# 运行全部 10 个样例
python evals/run_evals.py

# 运行指定样例
python evals/run_evals.py bug1 bug3

# 额外保存一份 JSON 结果
python evals/run_evals.py --output evals/results.json
```

每次评估会创建一个独立的运行目录：

```text
evals/runs/<run_id>/
├── results.json          # 本次 eval 的汇总结果
└── cases/
    ├── bug1.json         # 单个 case 的运行证据
    └── ...
```

`results.json` 记录 run metadata、每个 case 的分数、运行状态、`TeamProtocol` 摘要、问题列表、补丁说明、验证结果和 sandbox diff 摘要。`--output` 会额外写入一份兼容旧用法的 JSON。

评分满分 100：

| 维度 | 分值 | 说明 |
| --- | ---: | --- |
| Fix Correctness | 50 | 修复后的文件能以 exit code 0 运行 |
| Bug Completeness | 20 | 每个样例的 checker 通过比例 |
| Patch Minimality | 15 | 根据补丁改动行数评分 |
| Efficiency | 15 | 根据 retry 次数和耗时扣分 |

当前 golden dataset 包含 10 个文件，每个文件 3 个 planted bugs，共 30 个检查点。覆盖范围包括类型错误、文件 IO、编码、可变默认参数、迭代器、线程安全、datetime、递归、API payload、环境配置、集合边界、序列化和路径处理等常见问题。

### 评估结果分析

评估完成后，可以使用只读 reviewer agent 生成复盘报告：

```bash
python evals/review_results.py evals/runs/<run_id>/results.json
```

该命令会在同一运行目录下生成 `eval_review.md`，分析失败 case 可能对应的阶段，包括 reproduce、analyse、fix、verify、prompt/tooling 和 dataset/checker。

基于复盘报告生成改进计划：

```bash
python evals/propose_improvements.py evals/runs/<run_id>/eval_review.md
```

该命令会生成 `improvement_plan.md`，列出建议修改、原因、风险和验收方式。该步骤只生成报告，不会修改 `autodebug/`、`evals/scorer.py` 或 `evals/golden_dataset.py`。

## LangGraph 版本

`langgraph_version/` 提供同一流水线的 LangGraph 实现。该版本使用 `StateGraph` 表达阶段节点和条件边，并使用 `interrupt()` 实现人工审批。

安装额外依赖：

```bash
pip install -r langgraph_version/requirements_lg.txt
```

启动：

```bash
python langgraph_version/main_lg.py
```

LangGraph CLI 支持：

| 命令 | 说明 |
| --- | --- |
| `debug <file>` | 运行 LangGraph 调试流水线 |
| `memory` | 查看历史修复记忆 |
| `graph` | 打印 Mermaid 拓扑 |
| `tasks` | 查看任务看板 |
| `/history` | 查看消息总线记录 |
| `help` | 显示帮助 |
| `q` / `exit` | 退出 |

主版本便于阅读手写 orchestrator；LangGraph 版本便于对照 checkpoint、interrupt 和条件循环的表达方式。

## 兼容性说明

项目使用 Anthropic SDK，并支持 Anthropic-compatible base URL。使用 MiniMax M2.5 时，响应内容中可能包含 `ThinkingBlock`，读取最终文本时应检查 block 类型：

```python
getattr(block, "type", None) == "text"
```

不应使用 `hasattr(block, "text")` 判断文本块，因为 `ThinkingBlock` 也可能带有 `.text` 属性。

## 延伸阅读

- `GUIDE.md`：更完整的实现讲解。
- `DEVLOG.md`：构建过程和设计取舍。
- `sample_bugs/ANSWERS.md`：内置样例参考答案。
