# Auto-Debug Agent：四阶段自动修复流水线

> *"发现 bug 容易，修干净难——让四个专家分工比让一个全才更可靠。"*
>
> **核心思路**：Reproducer → Analyst → Fixer → Verifier，每阶段独立子 Agent，用 TeamProtocol 消息传接力棒。

---

## 问题

你有一个 Python 文件报错了。让单个 Agent "帮我修一下这个 bug" 有几个问题：

1. **上下文混乱**：复现、分析、修复、验证的对话全堆在一起，Agent 容易在某步中迷失。
2. **没有隔离**：Agent 直接改原文件，改坏了没法回退。
3. **没有记忆**：同一类 bug 下次出现又要从头分析。
4. **没有问责**：不知道哪一步失败了，也不知道失败原因。

## 解决方案

```
[User: "debug sample_bugs/bug1.py"]
         │
         ▼
┌─────────────┐  error_info  ┌─────────────┐
│  Reproducer │─────────────►│   Analyst   │
│             │              │             │
└─────────────┘              └──────┬──────┘
                                    │ root_cause
                                    ▼
┌─────────────┐  test_result ┌─────────────┐
│  Verifier   │◄─────────────│    Fixer    │
│             │              │             │
└─────────────┘              └─────────────┘
```

每个 Agent 只做一件事，通过 `TeamProtocol` dataclass 传递结构化消息，运行时状态全部持久化到 `.debug/` 目录。

---

## 工作原理

### 0. 模块分工

| 文件 | 职责 | 行数 |
|------|------|------|
| `config.py` | 全局常量，唯一修改 MODEL/URL 的地方 | ~25 |
| `protocol.py` | TeamProtocol dataclass + bus_write/read | ~50 |
| `tasks.py` | 任务看板 CRUD | ~25 |
| `memory.py` | FixMemory 类 | ~55 |
| `sandbox.py` | Sandbox 类 | ~35 |
| `tools.py` | 12 个工具函数（含 load_skill）+ schema 定义 | ~220 |
| `skills.py` | SkillLoader 类，两层按需加载 skills/ 目录 | ~65 |
| `pipeline.py` | run_subagent() + 4 个 Agent 函数 | ~190 |
| `main.py` | 编排器 + CLI | ~120 |

### 1. TeamProtocol 消息

四个 Agent 之间不传自由文本，传一个类型化的 dataclass：

```python
@dataclass
class TeamProtocol:
    phase:       str   # "reproduce" | "analyse" | "fix" | "verify"
    status:      str   # "ok" | "error" | "skip"
    target_file: str
    error_info:  str   # 复现阶段抓到的完整 traceback
    root_cause:  str   # 分析阶段的诊断结论
    fix_plan:    str   # 修复计划
    patch_desc:  str   # 补丁描述（给下一阶段和人类看）
    test_result: str   # 验证结果
    retry_count: int
```

每阶段结束后写入 `.debug/bus/` 目录（JSONL），可随时审计。

### 2. 子 Agent 运行器

每个阶段都是一次隔离的 `run_subagent()` 调用——独立的消息历史，
避免前一阶段的对话污染后一阶段的判断：

```python
def run_subagent(system, initial_prompt, tools, tool_handlers, label):
    messages = [{"role": "user", "content": initial_prompt}]
    while True:
        response = client.messages.create(
            model=MODEL, system=system, messages=messages,
            tools=tools, max_tokens=MAX_TOKENS,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            # 返回最终文本
            return next(
                (getattr(b, "text", "") for b in response.content
                 if getattr(b, "type", None) == "text"), ""
            )
        # 执行工具，追加结果…
```

> ⚠️ MiniMax M2.5 注意：API 返回 `ThinkingBlock` 对象，**不能**用
> `hasattr(block, "text")`，必须用 `getattr(block, "type", None) == "text"`。

### 3. 技能注入

`skills.py` 实现 `SkillLoader` 类，采用**两层按需加载**策略：

**Layer 1（廉价，始终加载）**：系统 prompt 只放 skill 名称和一句话描述，约 80 tokens：

```
Skills available (call load_skill('<name>') to load full instructions):
  - fixer: Apply minimal, safe patches to fix diagnosed Python bugs...
  - log-parser: Parse and interpret Python tracebacks...
  - static-analysis: Diagnose the root cause of a Python bug...
```

**Layer 2（按需，Agent 主动调用）**：Agent 通过 `load_skill("name")` 工具调用拉取完整内容，以 `<skill>` XML 标签包裹返回：

```python
# Agent 调用 load_skill("fixer") 时返回：
"""<skill name="fixer">
# Fixer Skill
## Pre-Edit Checklist
- [ ] Read first...
...
</skill>"""
```

每个 Agent 的 prompt 引导其先调用相关 skill：

```
1. Call load_skill('log-parser') to load traceback parsing instructions.
2. Call load_skill('static-analysis') then load_skill('log-parser').
1. Call load_skill('fixer') to load the mandatory edit checklist.
```

| 技能 | 引导给 | 内容 |
|------|--------|------|
| `log-parser` | Reproducer + Analyst | 异常类型映射、结构化输出格式、分析工作流 |
| `static-analysis` | Analyst | 10 类 bug 检查表、常见 fix 模式、根因输出格式 |
| `fixer` | Fixer | 强制 read→check→TODO→edit→check→read-back 流程 |

### 4. 沙箱隔离

Fixer 不碰原文件——先把目标文件复制到 `.debug/sandbox/`，
所有 write_file / edit_file 都限制在沙箱目录内：

```python
class Sandbox:
    def setup(self):
        shutil.copy2(self.original, self.sandbox_file)

    def apply_to_original(self):
        shutil.copy2(self.sandbox_file, self.original)

# Fixer 的 tool_handlers 里 root 固定为 sandbox_dir：
"edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"],
                                    kw["new_text"], root=sb),
```

### 5. 权限门

Fixer 完成后，流水线**暂停**，展示根因和补丁描述，等待人工确认：

```python
def ask_permission(msg: TeamProtocol) -> bool:
    print(f"Root cause: {msg.root_cause[:300]}")
    print(f"Proposed fix: {msg.patch_desc[:300]}")
    answer = input("Apply fix? [y/N]: ").strip().lower()
    return answer == "y"
```

### 6. 记忆系统

验证通过后，把 `(error_signature, root_cause, fix_summary)` 写入
`.debug/memory/index.jsonl`。下次遇到相似 traceback，
记忆匹配（≥3 个关键词重合）会自动注入 Analyst 的 system prompt 作为初始假设：

```python
def lookup(self, error_snippet: str) -> Optional[dict]:
    words = set(re.findall(r"\w+", error_snippet.lower()))
    for entry in self._entries():
        sig_words = set(re.findall(r"\w+", entry["error_signature"].lower()))
        if len(words & sig_words) >= 3:
            return entry
    return None
```

### 7. 自主重试

Verifier 失败后，Orchestrator 不直接放弃——把失败信息追加进 `root_cause`，
自动再调 Fixer（默认最多 `max_fix_attempts=4` 次）：

```python
for attempt in range(1, max_fix_attempts + 1):
    msg = fixer_agent(msg, sandbox)
    if not ask_permission(msg):
        return
    msg = verifier_agent(msg, sandbox)
    if msg.status == "ok":
        break
    # 把失败原因喂回 root_cause，让下一次 Fixer 更有针对性
    msg.root_cause += f"\n\n[Retry {attempt}] Previous fix failed:\n{msg.test_result}"
```

### 8. 错误恢复

`run_subagent()` 内置三层恢复：

| 情况 | 策略 |
|------|------|
| `stop_reason == "max_tokens"` | 注入续写消息，重试最多 3 次 |
| API 连接/限速错误 | 指数退避（最长 30 秒），重试最多 3 次 |
| 上下文超 TOKEN_THRESHOLD | 调用 `auto_compact()` 压缩历史 |

---

## 目录结构

```
auto-debug-agent/
├── main.py              ← 入口 + 编排器（~120 行）
├── requirements.txt    ← 基础依赖
├── autodebug/               ← 核心包
│   ├── __init__.py
│   ├── config.py        ← 共享常量：WORKDIR, client, MODEL, 目录路径
│   ├── protocol.py      ← TeamProtocol dataclass + 消息总线函数
│   ├── tasks.py         ← 四阶段任务看板（.debug/tasks.json）
│   ├── memory.py        ← FixMemory 跨会话记忆
│   ├── sandbox.py       ← Sandbox 沙箱隔离
│   ├── tools.py         ← 全部 12 个工具函数（含 load_skill）+ 每 Agent 的 schema 列表
│   ├── skills.py        ← SkillLoader 类：扫描 skills/ 目录，提供两层加载接口
│   └── pipeline.py      ← run_subagent() + 四个阶段 Agent 函数
├── langgraph_version/   ← LangGraph 实现（可对比版本）
│   ├── state.py         ← DebugState TypedDict
│   ├── nodes.py         ← 五个节点函数，复用 autodebug/ 中的 agent 函数
│   ├── graph.py         ← StateGraph 组装 + 条件边 + MemorySaver
│   ├── main_lg.py       ← LangGraph 版 CLI 入口
│   └── requirements_lg.txt  ← 额外依赖（langgraph）
├── skills/              ← 技能目录
│   ├── log-parser/SKILL.md
│   ├── static-analysis/SKILL.md
│   └── fixer/SKILL.md
├── sample_bugs/
│   ├── bug1.py          ← IndexError · KeyError · TypeError
│   ├── bug2.py          ← RecursionError · 逻辑错误 · ZeroDivisionError
│   ├── bug3.py          ← FileNotFoundError · AttributeError · 编码
│   ├── bug4.py          ← 类状态 · 可变默认参数 · __str__ 类型
│   └── bug5.py          ← 线程竞态 · generator 耗尽 · datetime 时区
├── evals/               ← 评估框架
│   ├── golden_dataset.py
│   ├── scorer.py
│   └── run_evals.py
└── .debug/              ← 运行时自动生成
    ├── bus/             ← TeamProtocol 消息（JSON 文件，可审计）
    ├── memory/
    │   └── index.jsonl  ← 跨会话修复记忆
    ├── sandbox/         ← Fixer 的隔离副本
    └── tasks.json       ← 四阶段任务看板
```

---

## 工具清单（tools.py）

| 工具 | 使用方的 Agent | 描述 |
|------|--------------|------|
| `bash` | 全部 | 运行任意 shell 命令 |
| `read_file` | 全部 | 读文件（可限制行数）|
| `write_file` | Fixer | 覆盖写文件 |
| `edit_file` | Fixer | 替换文件中的精确子串 |
| `list_dir` | Reproducer, Analyst | 列出目录内容和文件大小 |
| `search_code` | Analyst | 在单个文件内正则搜索 |
| `grep_files` | Analyst | 在目录下所有 .py 文件中正则搜索 |
| `python_check` | Reproducer, Fixer, Verifier | 不执行只做语法检查 |
| `run_tests` | Verifier | 运行 pytest 测试套件 |
| `git_diff` | Verifier | 查看 git diff 确认改动范围 |
| `view_traceback` | Reproducer, Analyst | 把 traceback 解析成结构化报告 |
| `load_skill` | 全部 | 按需加载完整技能内容 |

---

## 快速上手

```bash
cd /Users/hanhui/agents-from-scratch/auto-debug-agent
python main.py
```

提示符出现后试试：

```
debug >> debug sample_bugs/bug1.py    # 运行完整流水线
debug >> memory                        # 查看历史修复记忆
debug >> tasks                         # 查看当前任务看板
debug >> /history                      # 查看消息总线最近事件
debug >> help                          # 查看所有命令
```

### 预期输出

```
▶ Phase 1: Reproducer

  ┌─ [reproducer] bash  (python sample_bugs/bug1.py) ─
  │ Traceback (most recent call last):
  │   File "bug1.py", line 8, in <module>
  │ IndexError: list index out of range
  └────────────────────────────────────────

  Error detected: IndexError: list index out of range

▶ Phase 2: Analyst

  ┌─ [analyst] view_traceback  (Traceback (most recent...) ─
  │ Exception : IndexError
  │ Location  : bug1.py line 8
  └────────────────────────────────────────

  Root cause: • Line 8: items[len(items)] 应为 items[len(items)-1]...

╔══════════════════════════════════════════╗
║        Permission Required          ║
╚══════════════════════════════════════════╝
Apply fix? [y/N]: y

▶ Phase 4: Verifier
  ✓ PASS

[Memory] Fix pattern saved for future sessions.
Copy fix to original file? [y/N]: y
```

---

## LangGraph 版本

项目包含一个 `langgraph_version/` 目录，用 LangGraph 实现相同的四阶段流水线。

### 运行

```bash
pip install -r langgraph_version/requirements_lg.txt
python langgraph_version/main_lg.py
```

提示符变为 `debug-lg >>`，支持额外命令：

```
debug-lg >> graph    # 输出 Mermaid 拓扑图
```

### 与原版的主要差异

| 方面 | 原版 | LangGraph 版 |
|------|------|--------------|
| 状态传递 | `TeamProtocol` 手动传参 | `DebugState` TypedDict，自动合并 |
| 权限门 | `input()` 阻塞 | `interrupt()` 挂起图，可异步恢复 |
| 崩溃恢复 | 无 | `MemorySaver` checkpoint |
| 重试循环 | `for` 循环 | 条件边图内循环 |
| 拓扑可视化 | 无 | `draw_mermaid()` |
