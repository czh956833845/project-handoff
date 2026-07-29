# Project Handoff

> 为 AI 编程 Agent 提供可恢复、抗冲突、跨客户端的项目工作交接。

`project-handoff` 把项目当前状态保存在固定文件
`docs/project/HANDOFF.md`。当对话被压缩、任务暂停、切换会话或更换
Agent 时，新的上下文可以从一份简洁、可验证的“项目接力本”继续工作。

它不是聊天记录备份工具。它只维护继续项目真正需要的目标、边界、决定、
已完成工作、验证证据、当前文件、未完成事项和下一步。

## 解决的问题

- 上下文压缩后忘记已经完成的工作和关键决定；
- 新会话重新扫描整个项目；
- 多个 Agent 同时写交接文档，旧状态覆盖新状态；
- 写入中断，只留下半份损坏文档；
- 只有“已经完成”的描述，没有测试和构建证据；
- 历史不断堆积，最后变成聊天流水账。

## 核心能力

- 项目开始或恢复时优先读取 `docs/project/HANDOFF.md`；
- 文件不存在时根据模板创建；
- 固定维护八类当前状态；
- 重要阶段、暂停和可检测压缩前刷新；
- 压缩后的第一项项目动作必须重新读取；
- SHA-256 compare-and-swap 防止旧状态覆盖；
- POSIX/Windows 文件锁；
- 临时文件、`fsync` 和原子替换；
- 保留最近 50 个被替换版本；
- 压缩事件保存精确紧急快照和 pending marker；
- 禁止把令牌、密码、凭证写入交接文档。

## 交接文档结构

每份 `HANDOFF.md` 固定维护：

1. `Project goal`
2. `Scope and boundaries`
3. `Key decisions`
4. `Completed work`
5. `Verification evidence`
6. `Current files`
7. `Open items`
8. `Next step`

`Recent updates` 只保留最近少量里程碑，不复制完整对话。

## 文件布局

```text
docs/project/
├── HANDOFF.md
├── .HANDOFF.lock
├── .handoff-precompact-pending.json
├── handoff-history/
└── handoff-emergency/
```

## 客户端支持

| 客户端 | 当前能力 | 平台 |
| --- | --- | --- |
| Codex | 项目级强制调用；无预告信号时使用阶段结束和暂停检查点 | macOS、Linux、Windows |
| Kimi Code CLI | 原生 `PreCompact`，覆盖手动和自动压缩 | macOS、Linux |
| Claude Code | 原生 `PreCompact`，用户级或项目级安装 | macOS、Linux、Windows |
| Gemini CLI | 原生 advisory `PreCompress`，用户级或项目级安装 | macOS、Linux、Windows |
| GitHub Copilot | CLI 用户/项目模式；Cloud Coding Agent 仓库模式 | macOS、Linux、Windows、Cloud Linux |
| Qwen Code | 原生 `PreCompact`，用户级或项目级安装 | macOS、Linux、Windows |
| Cline | 已接线生命周期兜底；预备 `PreCompact` 适配器 | macOS、Linux |

### Cline 的准确边界

Cline 当前官方仓库已经定义 `PreCompact` 类型和模板，但同时明确标注
“coming soon”和“not wired”。因此本项目不会声称 Cline 已经具备真正的
压缩前感知。

Cline 安装器会提供：

- `TaskStart`
- `TaskResume`
- `TaskComplete`
- `SessionShutdown`
- 为上游接线后准备的 `PreCompact`

前四项用于阶段保存和恢复提醒。Cline 官方当前也注明文件 Hook 不支持
Windows，所以安装器会明确报告限制，不生成无法运行的假配置。

## 要求

- Python 3.10 或更高版本；
- 下载后的 `project-handoff/` 目录保持完整；
- 使用项目级 Hook 时，目标项目必须信任并允许对应客户端运行 Hook。

## 安装到 Codex

```bash
mkdir -p ~/.codex/skills
cp -R project-handoff ~/.codex/skills/project-handoff

python3 ~/.codex/skills/project-handoff/scripts/install_global_rule.py \
  --agents-file ~/.codex/AGENTS.md
```

全局规则安装器只管理带 `project-handoff` 标记的块。

## 接入 Kimi Code CLI

```bash
python3 /absolute/path/to/project-handoff/scripts/install_kimi_hook.py \
  --config-file ~/.kimi-code/config.toml \
  --skill-root /absolute/path/to/project-handoff
```

## 统一客户端安装器

以下命令都由下载本仓库的用户自行运行。本项目的开发测试不会修改维护者
电脑上的 Claude、Gemini、Copilot、Cline 或 Qwen 配置。

### Claude Code

```bash
python3 project-handoff/scripts/install_client_hook.py install \
  --client claude --scope user

python3 /path/to/project-handoff/scripts/install_client_hook.py install \
  --client claude --scope project --project-root /path/to/project
```

### Gemini CLI

```bash
python3 project-handoff/scripts/install_client_hook.py install \
  --client gemini --scope user

python3 /path/to/project-handoff/scripts/install_client_hook.py install \
  --client gemini --scope project --project-root /path/to/project
```

### GitHub Copilot CLI

```bash
python3 project-handoff/scripts/install_client_hook.py install \
  --client copilot --scope user

python3 /path/to/project-handoff/scripts/install_client_hook.py install \
  --client copilot --scope project --project-root /path/to/project
```

### GitHub Copilot Cloud Coding Agent

```bash
python3 /path/to/project-handoff/scripts/install_client_hook.py install \
  --client copilot --scope cloud --project-root /path/to/project
```

Cloud 模式会把最小运行时复制到目标项目
`.github/hooks/project-handoff/`，并生成仓库相对路径配置。云端因此不依赖
用户电脑上的 Skill 目录。生成文件需要提交到目标仓库。

### Cline

```bash
# Cline CLI 用户级
python3 project-handoff/scripts/install_client_hook.py install \
  --client cline --scope user

# Cline 编辑器用户级
python3 project-handoff/scripts/install_client_hook.py install \
  --client cline --scope editor

# 同时生成 CLI 和编辑器项目级兜底 Hook
python3 /path/to/project-handoff/scripts/install_client_hook.py install \
  --client cline --scope project --project-root /path/to/project
```

### Qwen Code

```bash
python3 project-handoff/scripts/install_client_hook.py install \
  --client qwen --scope user

python3 /path/to/project-handoff/scripts/install_client_hook.py install \
  --client qwen --scope project --project-root /path/to/project
```

## 检查与卸载

把安装命令中的 `install` 改成 `doctor` 即可检查：

```bash
python3 project-handoff/scripts/install_client_hook.py doctor \
  --client claude --scope user
```

只有配置存在且与当前版本一致时，`doctor` 才返回成功。

把动作改成 `uninstall` 会只移除本项目拥有的配置项或文件：

```bash
python3 project-handoff/scripts/install_client_hook.py uninstall \
  --client claude --scope user
```

安装器保留无关配置、拒绝损坏的 JSON、支持重复执行。Cline 遇到同名但不
属于本项目的 Hook 时会停止；只有在检查并明确接受覆盖时才使用 `--force`。

完整路径、事件字段和平台说明见
[`project-handoff/references/client-integrations.md`](project-handoff/references/client-integrations.md)。

## Hook 实际做什么

原生压缩事件发生时：

1. 客户端把 JSON 事件发送给适配器；
2. 适配器找到项目中的 `docs/project/HANDOFF.md`；
3. 精确复制当前字节到 `handoff-emergency/`；
4. 原子写入 `.handoff-precompact-pending.json`；
5. 客户端继续压缩；
6. 新上下文首先读取正式交接文档，再核对快照。

Hook 不读取完整聊天记录，也不会假装能在压缩前自动理解全部对话并语义
改写 `HANDOFF.md`。语义更新仍由 Agent 在重要阶段完成。

## 安全更新

先取得当前版本：

```bash
python3 project-handoff/scripts/update_handoff.py revision \
  --project-root /absolute/path/to/project
```

准备完整的新文档后：

```bash
python3 project-handoff/scripts/update_handoff.py update \
  --project-root /absolute/path/to/project \
  --content-file /absolute/path/to/new-HANDOFF.md \
  --expected-revision SHA256_OR_ABSENT
```

如果其他 Agent 已经更新，命令会报告冲突。必须重新读取并合并，不能直接
覆盖。

## 验证

```bash
python3 -m unittest discover \
  -s project-handoff/tests \
  -p 'test_*.py'
```

测试覆盖原子替换、POSIX/Windows 锁、并发冲突、50 个历史版本、事件
归一化、配置保留、重复安装、doctor、卸载、Copilot Cloud 自包含运行时、
Cline 生命周期兜底和临时目录隔离。

## 设计边界

- 不保存完整聊天记录；
- 不自动语义合并两个 Agent 的冲突决定；
- 不提供跨机器分布式锁；
- 没有真实压缩事件时，不宣称具备压缩前检查点；
- 紧急快照是恢复证据；
- `docs/project/HANDOFF.md` 始终是唯一当前权威状态。
