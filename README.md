# Auto-Debug Agent

自动化 Bug 修复 Agent — 四阶段多智能体流水线

## 项目结构

```
auto-debug-agent/
├── main.py              ← 入口，只有这一个文件在根目录
├── autodebug/               ← 核心包
│   ├── __init__.py
│   ├── config.py        ← 全局常量（API、路径、限额）
│   ├── protocol.py      ← TeamProtocol dataclass + 消息总线
│   ├── tasks.py         ← 四阶段任务看板 I/O
│   ├── memory.py        ← FixMemory 跨会话记忆
│   ├── sandbox.py       ← Sandbox 沙箱隔离
│   ├── tools.py         ← 12 个工具函数（含 load_skill）+ 每 Agent 的 schema 列表
│   ├── skills.py        ← SkillLoader：两层按需加载 skills/ 目录下的 SKILL.md
│   └── pipeline.py      ← run_subagent() + 四个 Agent 函数
├── skills/              ← 技能目录
│   ├── log-parser/SKILL.md
│   ├── static-analysis/SKILL.md
│   └── fixer/SKILL.md
├── sample_bugs/
│   ├── bug1.py          ← IndexError · KeyError · TypeError
│   ├── bug2.py          ← RecursionError · 逻辑错误 · ZeroDivisionError
│   ├── bug3.py          ← FileNotFoundError · AttributeError · 编码问题
│   ├── bug4.py          ← 类状态 · 可变默认参数 · __str__ 类型错误
│   └── bug5.py          ← 线程竞态 · generator 耗尽 · datetime 时区
├── evals/               ← 评估框架
│   ├── golden_dataset.py
│   ├── scorer.py
│   └── run_evals.py
└── .debug/              ← 运行时生成
    ├── bus/             ← 阶段间 TeamProtocol 消息（JSONL）
    ├── memory/          ← 跨会话修复记忆
    ├── sandbox/         ← 修复沙箱（隔离副本）
    └── tasks.json       ← 任务看板
```

## 设计特性

- **四阶段流水线**：每个 Agent 只做一件事，Reproducer → Analyst → Fixer → Verifier
- **独立子 Agent**：每阶段有独立消息历史，不互相污染
- **两层技能加载**：系统 prompt 只放描述，Agent 按需拉取完整技能内容
- **沙箱隔离**：Fixer 只改 `.debug/sandbox/` 副本，原文件不动
- **权限门**：写入前人工确认
- **跨会话记忆**：记住 error→fix 模式，下次遇到相似 bug 自动提示
- **自主重试**：Verifier 失败后自动重调 Fixer，最多 2 次
- **错误恢复**：max_tokens 续写 + API 指数退避 + 上下文压缩

## 使用方法

```bash
cd /Users/hanhui/agents-from-scratch/auto-debug-agent
python main.py
```

然后在提示符输入：

```
debug >> debug sample_bugs/bug1.py
```

## 流水线流程

```
[User: "debug sample_bugs/bug1.py"]
         │
         ▼
┌─────────────┐  error_info  ┌─────────────┐
│  Reproducer │ ────────────►│   Analyst   │
│             │              │             │
└─────────────┘              └──────┬──────┘
                                    │ root_cause
                                    ▼
┌─────────────┐  test_result ┌─────────────┐
│  Verifier   │◄─────────────│    Fixer    │
│             │              │             │
└─────────────┘              └─────────────┘
```

每个阶段的结果通过 `TeamProtocol` dataclass 传递，并写入 `.debug/bus/` 目录（JSONL，可审计）。

## 关键设计说明

### MiniMax M2.5 兼容性
API 返回 `ThinkingBlock` 对象，**不能**用 `hasattr(block, "text")` 检测文本块，
必须用 `getattr(block, "type", None) == "text"`。

### 权限门
Fixer 完成后，pipeline 暂停，展示根因和补丁描述，等待用户输入 `y` 才继续。

### 自主重试
Verifier 失败后，Orchestrator 将失败信息追加到 root_cause，
自动重新调用 Fixer，最多 `max_fix_attempts=2` 次。

### 记忆
验证通过后，将 `(error_signature, root_cause, fix_summary)` 写入
`.debug/memory/index.jsonl`，下次遇到相似错误时优先作为假设。

---

## LangGraph 版本

`langgraph_version/` 目录内包含同一流水线的 LangGraph 实现，可直接对比两种框架的写法差异。

| 方面 | 原版 | LangGraph 版 |
|------|------|--------------|
| 状态传递 | `TeamProtocol` dataclass 手动传参 | `DebugState` TypedDict，LangGraph 自动合并 |
| 权限门 | `input()` 阻塞等待 | `interrupt()` 挂起图，支持异步恢复 |
| 崩溃恢复 | 无 | `MemorySaver` checkpoint，相同 `thread_id` 可续跑 |
| 重试循环 | `main.py` 里的 `for` 循环 | 条件边 `verifier → fixer` 形成图内循环 |
| 拓扑可视化 | 无 | `app.get_graph().draw_mermaid()` |

运行方式：

```bash
python langgraph_version/main_lg.py
```
