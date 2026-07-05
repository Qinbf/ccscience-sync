# ccscience-sync

[English](README.md) | [中文](README.zh-CN.md)

让 Claude Science 自动使用你在 ccswitch 或 Claude Code 里选择的模型。

如果你不是程序员，只看前面这几步就够了。这个工具只需要安装一次。

## 最简单安装

安装前先确认：

1. 电脑里已经安装 Python 3.9 或更新版本。
2. Claude Science 至少打开过一次，然后可以先关掉。
3. ccswitch 或 Claude Code 里已经选好了你想用的模型。

### 第一步：下载

下载这个项目并解压：

[下载 ZIP](https://github.com/Qinbf/ccscience-sync/archive/refs/heads/main.zip)

### 第二步：安装

macOS：

双击 `install-macos.command`。

Windows：

双击 `install-windows.bat`。

### 如果双击不能运行

macOS 终端：

```sh
cd ~/Downloads/ccscience-sync-main
python3 ccscience_sync.py install
python3 ccscience_sync.py status
```

Windows PowerShell：

```powershell
cd "$env:USERPROFILE\Downloads\ccscience-sync-main"
py -3 .\ccscience_sync.py install
py -3 .\ccscience_sync.py status
```

## 怎么判断成功了

运行 `status` 后，看到类似下面两行就说明成功：

```text
helper: running (...)
runtime patch: installed (...)
```

之后正常使用 ccswitch 或 Claude Code 切模型即可。你新建 Claude Science
会话时，它会自动使用同步过来的模型。

## 平时怎么用

安装完成后，不需要再手动打开这个工具。

1. 在 ccswitch 或 Claude Code 里切换模型。
2. 新建 Claude Science 会话。
3. Claude Science 会自动使用同步后的模型。

如果 Claude Science 更新了，重新运行一次 `install`。

## 卸载

macOS：

双击 `uninstall-macos.command`。

Windows：

双击 `uninstall-windows.bat`。

## 常见问题

### 提示找不到 python 或 py

去 [python.org](https://www.python.org/downloads/) 安装 Python，然后重新打开
终端或 PowerShell，再运行安装命令。

### 提示找不到 Claude Science runtime

先打开一次 Claude Science，再关闭，然后重新运行 `install`。

### 模型没有立刻变化

请新建一个 Claude Science 会话。已经打开的旧会话可能会继续使用创建时的模型。

## 这个工具做了什么

`ccscience-sync` 是一个本地辅助工具。它会读取
`~/.claude/settings.json` 里的当前模型，把它转换成 Claude Science 使用的
模型 ID，然后在本机把 Claude Science 新会话的模型同步过去。

它不会读取、保存、打印、上传或在文档中记录 API key、密码、token 或其他凭据。

## 进阶用法

用 `pipx` 安装：

```sh
pipx install git+https://github.com/Qinbf/ccscience-sync.git
ccscience-sync install
ccscience-sync status
```

常用命令：

```sh
ccscience-sync model
ccscience-sync install
ccscience-sync status
ccscience-sync uninstall
```

直接从源码运行时：

- macOS：`python3 ccscience_sync.py <command>`
- Windows：`py -3 .\ccscience_sync.py <command>`

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

## 开发

```sh
python3 -m unittest discover -s tests
python3 -m py_compile ccscience_sync.py
```

## 许可证

MIT
