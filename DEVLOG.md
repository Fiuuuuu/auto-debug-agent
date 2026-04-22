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
    fix_plan:    str
    patch_desc:  str   # Fixer 填这个
    test_result: str   # Verifier 填这个
    retry_count: int
```

**关键决策**：`status` 字段。Reproducer 发现"没有错误"时返回 `status="skip"`，
Orchestrator 看到 skip 就直接结束，不走后面三个阶段。

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
| `git_diff` | 确认只改了预期的行，Verifier 用 |
| `view_traceback` | 把 traceback 解析为结构化报告，两个 Agent 用 |

**新增 `FIXER_SKILL`**：强制 Fixer 按顺序 `read → python_check → TODO → edit_file → python_check → read back`，避免盲目修改引入新语法错误。

---

## 整体复盘：这样设计好在哪里

| 设计决策 | 原因 |
|---------|------|
| 多文件模块化 | 面试官看 `tools.py` 就能一口气看清所有工具，不用扫全文 |
| `config.py` 单一入口 | 换 API endpoint / 模型只改一处 |
| TeamProtocol dataclass | 阶段间边界清晰，出问题一眼看哪个字段是空的 |
| 沙箱隔离 | 演示时不用担心改坏自己的文件 |
| 权限门 | 体现 Agent 的韧性，也让演示更有互动感 |
| 记忆系统 | 第二次 debug 同类 bug 时，Analyst 会说"上次也遇过这个" |
| 自主重试 | 体现 Agent 的韧性，不是遇到失败就停 |
| Skill 文本注入 | 每个 Agent 只拿自己需要的 skill，减少干扰 |

## 如果要继续扩展

1. **多文件支持**：现在只能 debug 单个文件，可以让 Reproducer 读 import 链
2. **Git 集成**：把沙箱换成真正的 git worktree，fix 可以直接 commit
3. **评估集**：给 sample_bugs/ 加更多 bug 样本，用 evals 框架跑批量评估
4. **Web UI**：把 TeamProtocol 消息流实时展示在浏览器里

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

### 4. `WORKDIR` 锚定为项目根
- **文件**：`autodebug/config.py`
- **问题**：`WORKDIR = Path.cwd()`，从非项目根目录启动时路径全部漂移。
- **修法**：改为 `Path(__file__).parent.parent.resolve()`，与启动目录无关。

### 5. Sandbox 子树镜像
- **文件**：`autodebug/sandbox.py`
- **问题**：只复制文件 basename 到扁平沙箱，资源文件（如 `config.json`）丢失，多目录同名文件互相覆盖。
- **修法**：按目标文件相对 WORKDIR 的路径镜像（`sandbox/sample_bugs/bug1.py`），并自动复制同目录资源文件。