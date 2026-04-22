# Auto-Debug Agent

一个四阶段多智能体调试流水线：给定一个有 bug 的 Python 文件，自动复现错误、定位根因、生成补丁、验证修复。

## 流水线

```
[debug sample_bugs/bug1.py]
        │
        ▼
┌──────────────┐  error_info   ┌──────────────┐
│  Reproducer  │──────────────►│   Analyst    │
│  运行文件     │               │  定位根因     │
└──────────────┘               └──────┬───────┘
                                      │ root_cause
                                      ▼
┌──────────────┐  test_result  ┌──────────────┐
│   Verifier   │◄──────────────│    Fixer     │
│  验证补丁     │               │  生成补丁     │
└──────────────┘               └──────────────┘
```

每个阶段结果通过 `TeamProtocol` dataclass 传递，并写入 `.debug/bus/`（可审计）。

## 项目结构

```
auto-debug-agent/
├── main.py                  ← CLI 入口 + Orchestrator（~130 行）
├── requirements.txt
├── autodebug/               ← 核心包
│   ├── config.py            ← 全局常量（API、路径、限额）
│   ├── protocol.py          ← TeamProtocol dataclass + 消息总线
│   ├── tasks.py             ← 四阶段任务看板 I/O
│   ├── memory.py            ← FixMemory 跨会话记忆
│   ├── sandbox.py           ← Sandbox 沙箱（子树镜像 + 资源文件复制）
│   ├── tools.py             ← 11 个工具函数 + 各 Agent 的 schema 列表
│   ├── skills.py            ← SkillLoader：两层按需加载
│   └── pipeline.py          ← run_subagent() + 四个 Agent 函数
├── langgraph_version/       ← 同一流水线的 LangGraph 实现（对比版）
│   ├── state.py
│   ├── nodes.py
│   ├── graph.py
│   ├── main_lg.py
│   └── requirements_lg.txt
├── skills/                  ← 技能文本目录
│   ├── log-parser/SKILL.md
│   ├── static-analysis/SKILL.md
│   └── fixer/SKILL.md
├── sample_bugs/             ← 内置测试用例
│   ├── bug1.py              ← KeyError · TypeError · ValueError
│   ├── bug2.py              ← 可变默认参数 · 缺少 return · __str__ 类型错误
│   ├── bug3.py              ← FileNotFoundError · AttributeError · UnicodeDecodeError
│   ├── bug4.py              ← 迭代时修改 dict · StopIteration · 无锁线程计数器
│   ├── bug5.py              ← naive/aware datetime · 无限递归 · Fibonacci 爆栈
│   └── ANSWERS.md           ← 答案手册（人类查阅用）
├── evals/                   ← 评估框架骨架
└── .debug/                  ← 运行时生成（已 .gitignore）
    ├── bus/                 ← 阶段间消息（JSONL）
    ├── memory/              ← 跨会话修复记忆
    ├── sandbox/             ← 修复沙箱（子树结构）
    ├── transcripts/         ← 上下文压缩前的完整对话存档
    └── tasks.json           ← 任务看板
```

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量（.env 文件或 export）
export ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic
export MODEL_ID=MiniMax-M2.5

# 3. 运行
python main.py
```

启动后在提示符输入：

```
debug >> debug sample_bugs/bug1.py
```

其他命令：

| 命令 | 说明 |
|------|------|
| `debug <file>` | 对指定 Python 文件运行完整流水线 |
| `memory` | 查看历史修复记忆（最近 10 条） |
| `tasks` | 查看当前阶段看板 |
| `/history` | 查看消息总线记录（最近 5 条） |
| `help` | 显示帮助 |
| `q` | 退出 |

## 设计亮点

| 特性 | 实现 |
|------|------|
| **四阶段隔离** | 每个 Agent 独立消息历史，不互相污染 |
| **沙箱隔离** | Fixer 只改 `.debug/sandbox/` 子树副本，原文件不动 |
| **权限门** | Fixer 完成后暂停，展示补丁描述，等待 `y` 确认 |
| **跨会话记忆** | 验证通过后记录 error→fix 模式，相似 bug 自动提示 |
| **自主重试** | Verifier 失败后将报错附加到 root_cause，自动重调 Fixer |
| **两层技能加载** | system prompt 只放描述，Agent 按需 `load_skill()` 拉取完整内容 |
| **两级上下文压缩** | micro_compact 截断旧 tool result（免费）；超限时 LLM 全量摘要 + 存档 |
| **结构化 verdict** | Verifier 输出 JSON `{"verdict":"PASS/FAIL"}`，消灭启发式字符串判断 |

## 工具清单

| 工具 | 使用方 | 说明 |
|------|--------|------|
| `bash` | 全部 | 运行 shell 命令 |
| `read_file` | 全部 | 读取文件（可限行数） |
| `write_file` | Fixer | 写入/覆盖文件 |
| `edit_file` | Fixer | 精确子串替换 |
| `list_dir` | Reproducer, Analyst | 列目录 |
| `search_code` | Analyst | 单文件正则搜索 |
| `grep_files` | Analyst | 跨文件正则搜索 |
| `python_check` | Reproducer, Fixer, Verifier | `py_compile` 语法检查 |
| `run_tests` | Verifier | 运行 pytest |
| `git_diff` | Verifier | 查看工作区变更 |
| `view_traceback` | Reproducer, Analyst | 解析 traceback 为结构化报告 |
| `load_skill` | 全部 | 按需加载技能文本 |

## LangGraph 版本

`langgraph_version/` 包含同一流水线的 LangGraph 实现：

| 方面 | 原版 | LangGraph 版 |
|------|------|--------------|
| 状态传递 | `TeamProtocol` dataclass 手动传参 | `DebugState` TypedDict，自动合并 |
| 权限门 | `input()` 阻塞等待 | `interrupt()` 挂起图，支持异步恢复 |
| 崩溃恢复 | 无 | `MemorySaver` checkpoint，相同 `thread_id` 可续跑 |
| 重试循环 | Orchestrator `for` 循环 | 条件边 `verifier → fixer` 形成图内循环 |
| 拓扑可视化 | 无 | `app.get_graph().draw_mermaid()` |

```bash
pip install -r langgraph_version/requirements_lg.txt
python langgraph_version/main_lg.py
```

## 兼容性说明

使用 MiniMax M2.5（Anthropic-compatible API）时，响应中包含 `ThinkingBlock` 对象。
检测文本块必须用：

```python
getattr(block, "type", None) == "text"   # ✅
hasattr(block, "text")                    # ❌ ThinkingBlock 也有 .text
```
