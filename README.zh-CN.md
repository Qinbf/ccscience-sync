# ccscience-sync

[English](README.md) | [中文](README.zh-CN.md)

把 ccswitch 或 Claude Code 当前选择的模型同步到 Claude Science。

`ccscience-sync` 是一个小型本地同步工具，适合已经用 ccswitch 切换
Claude Code 模型、同时希望 Claude Science 新会话自动使用同一模型的用户。

它不会读取、保存、打印、上传或在文档中记录 API key、密码、token 或其他凭据。

## 它能做什么

- 从 `~/.claude/settings.json` 读取 Claude Code 当前模型。
- 把该模型映射为 Claude Science 使用的模型 ID。
- 在本机启动 `127.0.0.1:19783` 辅助服务。
- 对 Claude Science 的网页运行时做可逆补丁。
- 同步 Claude Science 的默认模型和新会话请求中的模型字段。
- 支持 macOS 和 Windows，不需要管理员权限。

## 环境要求

- Python 3.9 或更新版本。
- Claude Code 或 ccswitch 会写入 `~/.claude/settings.json`。
- 已安装 Claude Science，并且至少启动过一次。

## 快速安装

使用 `pipx`：

```sh
pipx install git+https://github.com/Qinbf/ccscience-sync.git
ccscience-sync install
ccscience-sync status
```

从源码运行：

```sh
git clone https://github.com/Qinbf/ccscience-sync.git
cd ccscience-sync
python3 ccscience_sync.py install
python3 ccscience_sync.py status
```

Windows 用户请在 PowerShell 中运行：

```powershell
git clone https://github.com/Qinbf/ccscience-sync.git
cd ccscience-sync
py -3 .\ccscience_sync.py install
py -3 .\ccscience_sync.py status
```

## 常用命令

```sh
ccscience-sync model
ccscience-sync serve --port 19783
ccscience-sync install
ccscience-sync install --all
ccscience-sync install --no-autostart
ccscience-sync status
ccscience-sync uninstall
```

如果直接从源码运行，把 `ccscience-sync` 替换为
`python3 ccscience_sync.py`。Windows 用户使用 `py -3 .\ccscience_sync.py`。

## 各平台行为

| 平台 | 自启动方式 | 是否需要管理员权限 |
| --- | --- | --- |
| macOS | 用户级 LaunchAgent | 否 |
| Windows | 当前用户 Startup 文件夹 | 否 |

## 自定义模型映射

创建 `~/.ccscience-sync.json`：

```json
{
  "model_map": {
    "opus[1m]": "claude-opus-4-8",
    "sonnet[1m]": "claude-sonnet-5"
  }
}
```

默认映射：

| 源模型包含 | Claude Science 模型 |
| --- | --- |
| `opus` | `claude-opus-4-8` |
| `sonnet` | `claude-sonnet-5` |
| `sonnet-4`, `4.6` | `claude-sonnet-4-6` |
| `haiku` | `claude-haiku-4-5` |
| `fable` | `claude-fable-5` |

## Claude Science 数据目录

如果 Claude Science 的运行时文件不在默认位置，可以在安装前设置
`CLAUDE_SCIENCE_DATA_DIR`：

```sh
export CLAUDE_SCIENCE_DATA_DIR="/path/to/.claude-science"
ccscience-sync install
```

PowerShell：

```powershell
$env:CLAUDE_SCIENCE_DATA_DIR = "C:\path\to\.claude-science"
ccscience-sync install
```

## Claude Science 更新后

Claude Science 更新后可能会生成新的 runtime 目录。重新运行：

```sh
ccscience-sync install
```

## 卸载

```sh
ccscience-sync uninstall
```

这会移除 Claude Science runtime 补丁和辅助服务自启动项。它不会修改
Claude Code 设置、ccswitch 设置或任何 API 凭据。

## 工作原理

Claude Code 会把当前模型保存在 `~/.claude/settings.json`。Claude Science
会把默认模型保存在浏览器 localStorage 中，并在新建会话时发送 `model`
字段。`ccscience-sync` 通过两个本地组件把它们连接起来：

- 一个只监听本机的 JSON 辅助服务，用于返回映射后的模型；
- 一个写入 Claude Science `web-dist/index.html` 的带标记脚本补丁。

补丁会被 `ccscience-sync:start` 和 `ccscience-sync:end` 标记包裹，因此可以
安全更新或移除。

## 开发

```sh
python3 -m unittest discover -s tests
python3 -m py_compile ccscience_sync.py
```

## 安全说明

`ccscience-sync` 只读取本地模型元数据。请不要在 issue 或 pull request 中
提交 API key、密码、token 或其他私密凭据。

## 许可证

MIT
