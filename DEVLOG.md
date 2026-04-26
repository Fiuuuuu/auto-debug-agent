# 构建日志：Auto-Debug Agent

> 这个文件记录我怎么一步一步把这个项目从零写出来的——
> 包括每一步的思路、遇到的问题和怎么解决的。

---

## 第 0 步：先想清楚要做什么

**目标**：做一个能自动 debug Python 文件的 Agent，适合作为实习作品集展示。

**约束**：
- API 用 MiniMax M2.5（Anthropic-compatible），有 ThinkingBlock 问题
- 要覆盖常用的 multi-agent 核心模式，不能只是 toy project
- 代码风格要跟 `agents_new/` 系列完全一致

**一开始的疑问**：单个 Agent 写 `"debug this file"` 不就够了吗？

不够，原因三个：
1. 单 Agent 会把复现、分析、修复、验证的对话全混在一起，上下文一长就会"忘"前面做了什么
2. 没有隔离，改坏了没法回退
3. 没法展示 multi-agent 协作这个核心模式

所以决定做**四阶段流水线**：Reproducer → Analyst → Fixer → Verifier。

---

## 第 1 步：定义消息格式

最先想清楚的是：四个 Agent 之间怎么"交接棒"？

自由文本不行，因为下一个 Agent 不知道上一个说的哪句话是关键信息。
参考 TeamProtocol 的思路，定义一个 dataclass：

```python
@dataclass
class TeamProtocol:
    phase:       str
    status:      str   # "ok" | "error" | "skip"
    target_file: str
    error_info:  str   # Reproducer 填这个
    root_cause:  str   # Analyst 填这个
    issues:      list  # 已发现的运行时崩溃问题
    fix_plan:    str
    patch_desc:  str   # Fixer 填这个
    test_result: str   # Verifier 填这个
    retry_count: int
```

**关键决策**：`status` 字段。Reproducer 发现"没有错误"时返回 `status="skip"`，
Orchestrator 看到 skip 就直接结束，不走后面三个阶段。

后来加了 `issues` 字段。原因是单个 `root_cause` 字符串只适合"一次只暴露一个错误"，
但真实文件经常是第一个 traceback 修完后，第二个 traceback 才会出现。
`issues` 用简单 list/dict 记录多个运行时问题，保留教学项目的可读性，又能支持串行修复。

---

## 第 2 步：写 run_subagent()

四个 Agent 结构完全一样：给不同的 system prompt + tools，跑一个 agent loop，
返回最终文本。抽成一个函数避免重复：

```python
def run_subagent(system, initial_prompt, tools, tool_handlers, label):
    messages = [{"role": "user", "content": initial_prompt}]
    while True:
        response = client.messages.create(...)
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return next(
                (getattr(b, "text", "") for b in response.content
                 if getattr(b, "type", None) == "text"), ""
            )
        # 执行工具…
```

**踩坑 1：MiniMax M2.5 的 ThinkingBlock**

写完第一版用的是：
```python
# ❌ 错误写法
for b in response.content:
    if hasattr(b, "text"):
        return b.text
```

跑起来 `b` 是一个 `ThinkingBlock` 对象，它也有 `text` 属性（思考过程），
结果返回的是内部思考而不是最终回答。

正确写法要检查 `type` 字段：
```python
# ✅ 正确写法
getattr(b, "type", None) == "text"
```

这个坑在之前项目里踩过，所以这次第一版就直接用了正确写法。

---

## 第 3 步：写四个阶段 Agent

### Reproducer

最简单的一个：只需要 `bash` 和 `read_file`，让它跑文件抓 traceback。

**关键点**：怎么判断"有 error"？不能直接解析 LLM 的文字，
因为 LLM 可能用各种方式表达"没有错误"。

解决方案：检查结果文本里有没有 `"error"` 或 `"traceback"` 关键词，
或者有没有 `"no error found"` 字符串：

```python
status = "ok" if "error" in result.lower() or "traceback" in result.lower() else "skip"
if "no error found" in result.lower():
    status = "skip"
```

### Analyst

加入两个 skill并进化为两层按需加载：

- **Layer 1**：系统 prompt 里只放 skill 名称 + 一句话描述（~80 tokens）
- **Layer 2**：Agent 主动调用 `load_skill("log-parser")` / `load_skill("static-analysis")` 工具，才拉取完整内容返回到 tool_result

好处：不用的技能不浪费 token；skill 内容可以随时修改 SKILL.md 文件，不用动 Python 代码。

还要查记忆：如果 `.debug/memory/` 里有相似的历史修复，
把它作为"初始假设"注入 system prompt。

### Fixer

这个最复杂，有两个关键设计：

**沙箱**：先把目标文件复制到 `.debug/sandbox/`，
tool_handlers 里的 `edit_file` / `write_file` 的 root 参数固定为 sandbox 目录：
```python
"edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"], root=sb),
```

这样 Fixer 就算发疯乱写，也只会改沙箱里的副本，原文件绝对安全。

**权限门**：Fixer 跑完之后，流水线**不立刻**调 Verifier，
而是先暂停，打印出根因和补丁描述让人看，等用户输入 `y` 才继续。

### Verifier

跑沙箱里的文件，看有没有报错。结果里有 `"pass"` 就是成功。

**一个意外问题**：Verifier 的 `bash` 工具要在沙箱目录里运行，
但命令里的文件名是相对路径。解决方案：把沙箱目录作为 `cwd` 传进去：
```python
"bash": lambda **kw: run_bash(kw["command"], cwd=sb),
```

---

## 第 4 步：加错误恢复

直接参考三层策略，加进 `run_subagent()` 里：

```python
# 层 1：API 调用失败 → 指数退避重试
for attempt in range(MAX_RETRIES + 1):
    try:
        response = client.messages.create(...)
        break
    except APIError:
        time.sleep(BACKOFF_BASE * (2 ** attempt))

# 层 2：max_tokens → 注入续写消息
if response.stop_reason == "max_tokens":
    messages.append({"role": "user", "content": "Continue from where you stopped…"})
    continue

# 层 3：上下文过长 → auto_compact
if estimate_tokens(messages) > TOKEN_THRESHOLD:
    messages = auto_compact(messages, label)
```

---

## 第 5 步：加记忆系统

参考 `MemoryManager`，但简化很多——这里只存一个 JSONL 文件，
每行是 `{ts, error_signature, root_cause, fix_summary}`。

查找用关键词重叠计数，≥3 个词重合就认为是相似问题：

```python
def lookup(self, error_snippet):
    words = set(re.findall(r"\w+", error_snippet.lower()))
    for entry in self._entries():
        sig_words = set(re.findall(r"\w+", entry["error_signature"].lower()))
        if len(words & sig_words) >= 3:
            return entry
    return None
```

**为什么不用向量相似度？** 这是 teaching project，要让代码可读。
关键词重叠对于 Python 错误（`IndexError`, `list`, `index`, `range`）
这种技术词汇来说效果已经够好。

---

## 第 6 步：Orchestrator 自主重试

Verifier 失败后怎么办？

**方案 A（放弃）**：直接报告失败。——太简单，没有体现自主重试。

**方案 B（询问用户）**：问用户"要不要重试"。——打断了自动化流程。

**方案 C（自主决定）**：自动重试，但把失败信息喂回给 Fixer 让它知道上次哪里不对。

选方案 C。关键是把 Verifier 输出追加进 `root_cause`：

```python
for attempt in range(1, max_fix_attempts + 1):
    msg = fixer_agent(msg, sandbox)
    if not ask_permission(msg):
        return
    msg = verifier_agent(msg, sandbox)
    if msg.status == "ok":
        break
    # 失败了：把失败原因附加进去，让下次 Fixer 更有针对性
    msg.root_cause += f"\n\n[Retry {attempt}] Previous fix failed:\n{msg.test_result}"
```

权限门（`ask_permission`）还是留着，因为每次 Fixer 都可能生成不同的补丁，
都要给用户机会确认。

---

## 第 7 步：任务看板

四个阶段的状态写入 `.debug/tasks.json`，方便调试时看进度。
状态集合：`pending → in_progress → done / failed / skipped`。

```python
PHASES = ["reproduce", "analyse", "fix", "verify"]

def tasks_update(phase, status):
    t = tasks_load()
    t[phase] = status
    tasks_save(t)
    print(f"  [task] {phase} → {status}")
```

---

## 第 8 步：CLI 和整体收尾

主循环风格写，加上 `/history`、`memory`、`tasks`、`help` 几个诊断命令。

---

## 第 9 步：重构为多文件（可读性 + 更多工具）

单文件 500 行后，找一个类需要滚很长。按职责拆成 9 个文件：

| 文件 | 内容 |
|------|------|
| `config.py` | 全局常量，一处改全处生效 |
| `protocol.py` | TeamProtocol、bus_write、bus_read_latest |
| `tasks.py` | tasks_load / save / update |
| `memory.py` | FixMemory 类 |
| `sandbox.py` | Sandbox 类 |
| `tools.py` | 所有工具函数 + 每 Agent 的 schema 列表 |
| `skills.py` | LOG_PARSER / STATIC_ANALYSIS / FIXER 三段技能文本 |
| `pipeline.py` | run_subagent() + 四个 Agent 函数 |
| `main.py` | 编排器 + CLI，缩减到 ~120 行 |

**新增 6 个工具**（在 `tools.py` 里）：

| 工具 | 作用 |
|------|------|
| `list_dir` | 列目录，让 Reproducer 先看清项目结构 |
| `grep_files` | 跨文件正则搜索，Analyst 找全部调用占 |
| `python_check` | `py_compile` 语法检查，Fixer 改前改后各跑一次 |
| `run_tests` | pytest 整套测试，Verifier 用 |
| `sandbox_diff` | 比较原文件和沙箱文件，Verifier 用 |
| `view_traceback` | 把 traceback 解析为结构化报告，两个 Agent 用 |

**新增 `FIXER_SKILL`**：强制 Fixer 按顺序 `read → python_check → TODO → edit_file → python_check → read back`，避免盲目修改引入新语法错误。

---

## 第 10 步：清理课程痕迹

项目写完后，把所有和课程相关的文字全部清掉，让它看起来像一个独立的作品集项目，而不是练习作业：

- **`autodebug/*.py` 全部 8 个文件**：删除每个文件第二行的 `# Harness: xxx` 注释（这是课程脚手架的痕迹）
- **`main.py`**：删除 `# Harness:` 首行注释，以及各节点分割线注释里的 `(sXX)` 标签
- **`pipeline.py`**：删除 docstring 里的 `(s01)` / `(s06)` 等标签，删除函数内联注释里的 `(s04)` / `(s11)` 标签
- **`README.md`**：删除"演示的 s-file 模式"整张表格；删除流水线图中各框里的 `(s01+s02)` 等标签；删除章节标题里的 `（s07）`/`（s17）`/`（s09）` 括号；把 skills/ 目录注释里的"同 s05 约定"去掉；整个章节替换为"设计特性"列表
- **`GUIDE.md`**：删除所有章节标题里的 `（sXX）`，删除工具表里的 `(s05 Layer 2)`，删除"覆盖的 s-file 模式"整张表格，删除流水线图中的框内标签
- **`DEVLOG.md`**：把正文里所有"参考 s16 的思路"/"参考 s09 的…"/"体现 s17"等内联引用改写成直接描述

---

## 第 11 步：改善工具调用的终端输出

原来 `run_subagent()` 里每次工具调用只打一行：

```
  [analyst] bash: Traceback (most recent call last): ...
```

问题：工具名和结果混在一行，多个工具调用连在一起很难区分。

改法：把每次工具调用改成三段式展示：

```
  ┌─ [analyst] bash  (python sample_bugs/bug1.py) ─
  │ Traceback (most recent call last):
  │   File "bug1.py", line 8
  │ IndexError: list index out of range … (348 chars total)
  └────────────────────────────────────────
```

具体实现：
- **调用头** `┌─`：agent 标签（各自有颜色：reproducer=蓝、analyst=紫、fixer=黄、verifier=青）+ 工具名加粗 + 第一个入参的前 60 字符作为预览
- **结果体** `│`：逐行打印，输出超 300 字符时截断并提示总长度，错误内容自动变红
- **收口** `└─`：40 个破折号，视觉上把每次工具调用框成独立区块

---

## 第 12 步：LangGraph 版本

在 `langgraph_version/` 目录下写了同一个 pipeline 的 LangGraph 实现，作为对比版本：

**核心差异**：

| 方面 | 原版（`main.py`）| LangGraph 版（`main_lg.py`）|
|------|-----------------|---------------------------|
| 状态传递 | `TeamProtocol` dataclass 手动传参 | `DebugState` TypedDict，LangGraph 自动合并 |
| 权限门 | `input()` 阻塞等待 | `interrupt()` 挂起图，支持异步恢复 |
| 崩溃恢复 | 无 | `MemorySaver` checkpoint，相同 `thread_id` 可续跑 |
| 重试循环 | `main.py` 里的 `for` 循环 | 条件边 `verifier → fixer` 形成图内循环 |
| 拓扑可视化 | 无 | `app.get_graph().draw_mermaid()` 输出 Mermaid 图 |

**文件结构**：
- `state.py`：`DebugState` TypedDict，字段与 `TeamProtocol` 一一对应
- `nodes.py`：5 个节点函数，每个节点调原版 pipeline.py 里的 agent 函数，零重复
- `graph.py`：`StateGraph` 组装 + 条件边路由 + `MemorySaver` 编译
- `main_lg.py`：CLI + interrupt while 循环处理多次权限确认

**修复的两个问题**：
1. `_to_msg()` 里错误地读了 `DebugState` 里不存在的 `phase` 字段 → 直接置为 `""`
2. `analyst_node` 里的 `sandbox.setup()` 只调一次的设计意图没有注释 → 补充说明：retry 时 Fixer 故意从上一次改过的文件继续，而不是重头来；如需每次重置改为在 `fixer_node` 里调 `setup()`


---

## 第 13 步：sample_bugs 重写 + 答案分离

**背景**：原始 bug 文件注释里直接写了"BUG 1: ..."、"should be ..."，大模型通过 `read_file` 读到这些注释相当于直接看答案，失去诊断意义。

**改动**：

1. 重写 5 个 bug 文件，每个文件植入 3 个真实场景的 bug：
   - `bug1.py`：KeyError（缺失 dict key）、TypeError（None 参与运算）、ValueError（`int("3.0")`）
   - `bug2.py`：可变默认参数共享、缺少 `return`（隐式 None）、`__str__` 返回非字符串
   - `bug3.py`：硬编码绝对路径、AttributeError（int 调用字符串方法）、UnicodeDecodeError 风险
   - `bug4.py`：迭代时修改 dict、`next()` 无默认值、无锁线程计数器
   - `bug5.py`：naive vs aware datetime 比较、flatten 无基本情况无限递归、Fibonacci 无记忆化爆栈

2. 所有 bug 文件删除"BUG N:"、"should be..."等提示性注释，只保留正常的功能 docstring。

3. 新增 `sample_bugs/ANSWERS.md`：人类查阅的答案手册，每个文件一张表格，列出函数名、错误类型、修法。

---

## 第 14 步：五项工程质量修复

根据代码审查发现的问题，依次修复：

### 1. `sys.executable` 替换硬编码 `"python"`
- **文件**：`autodebug/tools.py`
- **问题**：`run_python_check`、`run_run_tests` 里硬编码 `["python", ...]`，在 venv / conda 环境下可能跑到系统解释器而非当前环境。
- **修法**：`import sys`，改为 `[sys.executable, ...]`。

### 2. Verifier 结构化 JSON verdict
- **文件**：`autodebug/pipeline.py`
- **问题**：`"pass" in result.lower()` 极脆，模型说"it didn't pass"也会误判为 PASS。
- **修法**：Verifier prompt 要求输出固定 JSON 块 `{"verdict": "PASS", "summary": "..."}` ，解析改为 `re.search + json.loads`。

### 3. `git_diff` cwd 改回项目根
- **文件**：`autodebug/pipeline.py`
- **问题**：Verifier handler 里 `run_git_diff(root=sb)`，沙箱目录不在任何 git 仓库里，每次都静默返回 `(no changes)`。
- **修法**：`root=WORKDIR`，diff 针对真实 repo 工作区。
- **后续**：第 16 步里彻底换成了 `sandbox_diff`，因为 Verifier 只需要看"原文件 vs 沙箱文件"，不应该被 pycache、主仓库其他改动干扰。

### 4. `WORKDIR` 锚定为项目根
- **文件**：`autodebug/config.py`
- **问题**：`WORKDIR = Path.cwd()`，从非项目根目录启动时路径全部漂移。
- **修法**：改为 `Path(__file__).parent.parent.resolve()`，与启动目录无关。

### 5. Sandbox 子树镜像
- **文件**：`autodebug/sandbox.py`
- **问题**：只复制文件 basename 到扁平沙箱，资源文件（如 `config.json`）丢失，多目录同名文件互相覆盖。
- **修法**：按目标文件相对 WORKDIR 的路径镜像（`sandbox/sample_bugs/bug1.py`），并自动复制同目录资源文件。

---

## 第 15 步：提示词质量改进 + 界面修复

### 1. 四个子 Agent 提示词重写为"强制顺序"风格
- **文件**：`autodebug/pipeline.py`
- **问题**：使用"Steps"风格的提示词时，模型感觉"信息已够"就会提前停止，跳过后续工具调用（如 Analyst 跳过 `grep_files`，Reproducer 完成后重新循环一遍）。
- **修法**：所有 4 个 Agent 改为 `"You MUST call tools in this exact order"` 风格，每一步加 `"Do NOT skip this step"`，最后一步加明确终止指令 `"IMMEDIATELY stop calling tools and write your final report"`。

### 2. Reproducer 循环重复执行
- **文件**：`autodebug/pipeline.py`
- **问题**：旧 prompt 说"call view_traceback to parse it"，但没有说调完之后做什么，模型在 `view_traceback` 后迷失，重新从第一步开始循环。
- **修法**：在 `view_traceback` 之后加 `"IMMEDIATELY stop calling tools and write your final report"`，并加 `"Do NOT restart from step 1"`。

### 3. Verifier 误判 FAIL
- **文件**：`autodebug/pipeline.py`
- **问题**：prompt 说"ran without the original error"，但模型把"输出值从 crash 变成 0.0"理解为"结果有问题" → 误判 FAIL。
- **修法**：明确补充 `"A changed output value is NOT a failure — that is the fix working. verdict=FAIL only if a traceback or the SAME exception still appears."`

### 4. `ask_permission` 显示裸 Markdown
- **文件**：`main.py`
- **问题**：`Root cause` 和 `Proposed` 字段直接 `[:300]` 截断，`---`、`**bold**`、代码块原样显示，可读性差。
- **修法**：内联 `_strip_md()` 函数，去掉代码块、标题、粗体、行内代码、分割线后将多行合并为 `|` 分隔的单行再截断。

### 5. Fixer / Verifier 缺少 `_print_summary`
- **文件**：`main.py`
- **问题**：Phase 3 和 Phase 4 完成后没有摘要框输出，用户看不到补丁内容和验证结果。
- **修法**：Fixer 完成后加 `_print_summary("Patch applied", msg.patch_desc, color="\033[33m")`；Verifier 完成后加 `_print_summary("Verification result", msg.test_result, color=绿/红)`。

---

## 第 16 步：主线流程升级为多问题追踪

**背景**：跑 `bug2` 到 `bug5` 后发现一个更真实的问题：
很多文件不是"修一个 root cause 就结束"，而是第一个崩溃修掉后，后面的代码路径才会继续暴露新的 traceback。

旧流程的问题在于：
- `root_cause` 只有一个字符串，无法稳定记录多个已发现问题。
- Verifier 有时会多次读文件、跑无关 git 命令，验证过程太发散。
- `git_diff` 会受到 pycache 或主仓库其他改动影响，不适合解释沙箱补丁。
- 默认只重试 2 轮，`bug3`、`bug4`、`bug5` 这种串行暴露错误的文件轮次不够。

这一步只改手写主线版本：`main.py + autodebug/*`。
LangGraph 版本只做最小兼容，保证还能导入和运行，不同步重构。

### 1. `TeamProtocol` 加 `issues`

- **文件**：`autodebug/protocol.py`
- **问题**：单个 `root_cause` 适合写摘要，但不适合做流程状态。
- **修法**：新增 `issues: list[dict]`，每个 issue 记录：
  - `exception_type`
  - `location`
  - `summary`
  - `status`
  - `attempt_found`

为什么用 list/dict，而不是新建复杂类？

因为这个项目是 teaching project，Agent 之间传递的状态应该一眼能看懂。
`issues` 是轻量结构化数据，既能 JSON 序列化写进 `.debug/bus`，又不会把项目变成一套复杂的数据模型。

### 2. Analyst 改成"当前 traceback + 全文件崩溃扫描"

- **文件**：`autodebug/pipeline.py`
- **问题**：旧 Analyst 主要解释当前 traceback，容易漏掉同文件里后续必崩的代码路径。
- **修法**：prompt 改成两段：
  - Part A：解释当前 traceback 的直接原因。
  - Part B：扫描全文件里类似的 runtime crash 风险。

这里特意限制为"会导致崩溃的风险"。

原因是验收标准是"运行不崩溃"，不是语义完全正确。
例如购物车是否真的清空、Counter 是否真正线程安全、fib 是否性能最佳，这些都可以作为人工 review 关注点，但不能让 Agent 在本轮为了语义完美而扩大修改范围。

### 3. Fixer 改成按 `issues` 修

- **文件**：`autodebug/pipeline.py`
- **问题**：旧 Fixer 只能看 `root_cause` 和 verifier 失败文本，容易把多轮错误混成一段自然语言。
- **修法**：Fixer prompt 注入已知 `issues`，要求优先修最新 verifier 暴露的新 traceback。

同一轮是否可以修多个问题？

可以，但有条件：Analyst 已经明确指出这些问题属于同类 runtime crash，而且修法是小改动。
这样能减少无意义的多轮 retry，但仍然避免一次性大重构。

### 4. Verifier 固定四步

- **文件**：`autodebug/pipeline.py`
- **问题**：Verifier 如果自由调用工具，会出现重复 `cat`、重复 `python`、无关 `git status`，验证成本高且结果不稳定。
- **修法**：Verifier prompt 固定只做四步：
  1. `python_check`
  2. `bash("python 目标文件")`
  3. `run_tests(".")`
  4. `sandbox_diff`

判定规则也收紧：
- 目标文件退出码为 0。
- 输出没有 traceback。
- 没有运行时异常。

满足这些才 `PASS`。
如果出现任何 traceback 或异常，直接 `FAIL`，并把新问题追加到 `issues`。

### 5. `run_subagent()` 增加工具预算

- **文件**：`autodebug/pipeline.py`
- **问题**：即使 prompt 写了"固定四步"，模型仍有可能继续调用工具。
- **修法**：`run_subagent()` 新增 `max_tool_calls` 参数。

Verifier 调用时传 `max_tool_calls=4`。
超过预算就返回失败文本，让 Orchestrator 进入 retry，而不是让 Verifier 长时间循环。

这里保留全局 `max_steps=30`，因为 Reproducer / Analyst / Fixer 仍然需要普通 agent loop。
只对 Verifier 单独收紧，是因为 Verifier 的任务本质上应该是确定性的检查流程。

### 6. 用 `sandbox_diff` 替换 `git_diff`

- **文件**：`autodebug/tools.py`
- **问题**：Verifier 只关心"沙箱文件相对原文件改了什么"，但 `git diff` 看的是整个工作区。
- **修法**：新增 `run_sandbox_diff()`，用标准库 `difflib.unified_diff()` 比较：
  - 原始目标文件
  - `.debug/sandbox/` 里的目标文件

这样输出天然聚焦在本次自动修复的 patch 上。
它不会显示 pycache，也不会混入用户在主仓库里的其他修改。

### 7. 默认 retry 从 2 调到 4

- **文件**：`main.py`
- **问题**：2 轮只够修一两个直接暴露的错误，不够覆盖串行崩溃。
- **修法**：`run_debug_pipeline(..., max_fix_attempts=4)`。

为什么不是无限重试？

因为这个项目的目标是自动 debug 的教学演示，不是无人值守修复系统。
4 轮能覆盖 `bug1/bug3/bug4/bug5` 这类逐步暴露 traceback 的文件，同时还能避免模型在错误方向上无限消耗 token。

### 8. LangGraph 版本最小兼容

- **文件**：`langgraph_version/state.py`
- **文件**：`langgraph_version/nodes.py`
- **文件**：`langgraph_version/graph.py`
- **文件**：`langgraph_version/main_lg.py`

只做必要适配：
- `DebugState` 增加 `issues`。
- `_to_msg()` / `_from_msg()` 传递 `issues`。
- `MAX_FIX_ATTEMPTS` 同步为 4。
- 初始 state 增加 `"issues": []`。

没有同步重写 LangGraph 逻辑。
原因是本轮目标是先把手写主线跑稳；LangGraph 版是对比实现，等主线接口稳定后再重构更安全。

### 9. 验证结果

本轮先做两层验证：

1. 本地无模型检查：
```bash
python -m py_compile autodebug/*.py langgraph_version/*.py main.py evals/run_evals.py
```

结果：通过。

2. 模型级 smoke test：
```python
run_debug_pipeline("sample_bugs/bug2.py", auto_approve=True)
```

结果：
- 最终 `status="ok"`。
- sandbox 里的 `bug2.py` 运行退出码为 0。
- 输出无 traceback。
- Verifier 只调用了固定四个工具。
- `sandbox_diff` 正确显示原文件和沙箱文件的 patch。
- 原始 `sample_bugs/bug2.py` 没有被写回。

这一步的核心收益：流程从"修一个字符串 root cause"升级成了"围绕多个 runtime issues 迭代"，但代码仍然保持简单、可读、适合讲解。

---

## 第 17 步：README 重写为作品集文档

**背景**：项目功能逐渐完整后，旧 README 已经不能准确表达当前实现。
它更像开发过程说明，缺少面向第一次阅读者的项目入口，也有一些过时信息。

本轮目标是把 README 改成适合展示的项目首页：
- 先说明项目做什么。
- 再展示四阶段流水线。
- 然后给快速开始、CLI、运行产物、evals 和 LangGraph 对照版本。
- 复杂设计细节只保留高信号摘要，详细教学内容继续放在 `GUIDE.md` 和 `DEVLOG.md`。

**主要调整**：

1. 删除"核心能力"式的营销列表，改成项目说明文档结构。
2. 重画流水线图，使 Reproducer / Analyst / Fixer / Verifier 的关系更清楚。
3. 更新真实实现事实：
   - `TeamProtocol` 已有 `issues` 字段。
   - 默认 `max_fix_attempts=4`。
   - Verifier 使用 `sandbox_diff` 和 JSON verdict。
   - `.debug/` 保存 bus、sandbox、memory、transcripts 和 task board。
4. README 语气从口语化说明改为正式项目文档。

这里的取舍是：README 不写成完整教程。
它的作用是让第一次打开项目的人快速理解项目目标、能跑起来，并知道从哪里继续读。

---

## 第 18 步：Evals 从脚本升级为小型评估 harness

**背景**：原来的 `evals/run_evals.py` 可以跑样例并给分，但输出 JSON 太薄。
如果一个 case 失败，只能看到分数，看不到 Agent 在哪一阶段失败、补丁是什么、Verifier 看到了什么。

为了让 evals 对项目展示更有说服力，本轮把 evals 拆成几个职责清晰的模块：

| 文件 | 作用 |
|------|------|
| `evals/run_evals.py` | CLI 入口，保持旧命令可用 |
| `evals/runner.py` | 复制样例、运行 pipeline、调用 scorer、写运行目录 |
| `evals/artifacts.py` | 生成 `results.json` 和单 case artifact |
| `evals/reporting.py` | 终端表格和颜色输出 |
| `evals/agent_reports.py` | Reviewer / Proposal 共用的只读模型调用 |
| `evals/review_results.py` | 根据 eval 结果生成 `eval_review.md` |
| `evals/propose_improvements.py` | 根据 review 和源码上下文生成 `improvement_plan.md` |

新的运行产物结构：

```text
evals/runs/<run_id>/
├── results.json
└── cases/
    ├── bug1.json
    └── ...
```

`results.json` 现在包含：
- run metadata
- 每个 case 的 score 和 grade
- `TeamProtocol` 摘要
- `issues`
- `patch_desc`
- `test_result`
- sandbox diff 摘要

**关键边界**：

Reviewer / Proposal Agent 只写报告，不直接修改 `autodebug/`、`evals/scorer.py` 或 `evals/golden_dataset.py`。
原因是 eval 的外层系统应该负责观测、评分和反馈；如果让改进 Agent 直接改裁判或试卷，结果就不可信。

**额外修复**：

评估工作副本最开始放在系统临时目录，但工具层有 workspace 路径限制。
这样 Agent 可能无法读取 eval 目标文件。

修法是把 eval 工作副本放到项目内：

```text
.debug/eval_work/<run_id>/
```

这样仍然不会修改原始样例，同时满足工具的路径安全约束。

---

## 第 19 步：sample_bugs 扩展到 10 个 case

**背景**：5 个样例适合作为 demo，但作为实习作品集展示，评估规模偏小。
每个文件有 3 个 planted bugs，5 个文件一共 15 个检查点，只能说明 pipeline 能跑通，不能充分说明覆盖面。

本轮把 `sample_bugs/` 从 5 个文件扩展到 10 个文件，共 30 个检查点。

新增样例：

| 文件 | 覆盖点 |
|------|--------|
| `bug6.py` | API payload、缺失字段、空列表聚合 |
| `bug7.py` | 环境变量、CLI 配置、`None` path |
| `bug8.py` | 集合边界、空输入、dict 新 key |
| `bug9.py` | JSON、CSV、datetime 序列化 |
| `bug10.py` | `Path` 对象、缺失父目录、缺失文件 |

同步更新：
- `evals/golden_dataset.py` 增加 5 个 case 的 checker。
- `sample_bugs/ANSWERS.md` 增加 bug6 到 bug10 的参考答案。
- `README.md` 中的评估规模改为 10 个文件、30 个检查点。

验证方式：

```bash
python -B -m py_compile sample_bugs/bug6.py sample_bugs/bug7.py sample_bugs/bug8.py sample_bugs/bug9.py sample_bugs/bug10.py evals/golden_dataset.py evals/runner.py
python -B evals/run_evals.py --help
```

还做了 checker sanity check：原始 10 个 bug 文件在对应 checker 下都是 `0/3`。
这说明 planted bugs 没有被误判为已修复。

---

## 第 20 步：稳定化 `main.py` 主流程

**背景**：主流程已经能工作，但还有几个工程质量问题：
- 文件不存在提示里多了一个 `h`。
- `target_file` 直接用 `Path(target_file)`，从非项目根目录启动时可能路径漂移。
- 如果某个 phase 抛出未捕获异常，pipeline 会直接中断，task board 和 sandbox 状态可能不清晰。
- CLI 入口直接写在 `if __name__ == "__main__"` 里，可读性一般。

本轮只做小范围稳定性改动，不改变四阶段 Agent 行为，也不新增 `python main.py debug <file>` 直跑模式。

### 1. 路径解析基于 `WORKDIR`

相对路径统一解析为：

```python
target = WORKDIR / target_file
```

这样无论用户从哪里启动，只要传入项目内相对路径，都会按项目根目录解析。

### 2. 异常兜底

`run_debug_pipeline()` 增加局部状态：

```python
msg = None
sandbox = None
attempt = 0
current_phase = None
```

任意阶段抛出未捕获异常时：
- 返回 `status="error"`。
- 返回值额外包含 `error` 字段。
- 当前 phase 标记为 `failed`。
- 如果 sandbox 已创建，自动 discard。

返回结构仍保持向后兼容，原有字段 `status`、`msg`、`sandbox`、`wall_time`、`retry_count` 继续保留。

### 3. REPL 入口提取为 `main()`

底部结构改为：

```python
def main() -> None:
    ...

if __name__ == "__main__":
    main()
```

交互命令保持不变：
- `debug <file>`
- `memory`
- `tasks`
- `/history`
- `help`
- `q` / `exit`

验证方式：

```bash
python -B -m py_compile main.py
python -B -c "from main import run_debug_pipeline, main; print(callable(main), callable(run_debug_pipeline))"
python -B -c "from main import run_debug_pipeline; r=run_debug_pipeline('not_exists.py'); print(r['status'])"
printf 'help\ntasks\nq\n' | python -B main.py
```

还用 monkeypatch 模拟 `reproducer_agent` 抛异常，确认会返回 `status="error"`，并把 `reproduce` 标记为 failed。

这一步的收益是：主入口不再只依赖"模型正常运行"这个理想条件。
即使某个阶段崩掉，调用方也能拿到结构化错误结果，`.debug/` 状态也不会留下明显误导。
