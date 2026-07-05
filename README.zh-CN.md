# ccscience-sync

[English](README.md) | [中文](README.zh-CN.md)

让 Claude Science 自动使用你在 ccswitch 或 Claude Code 里选择的模型。

普通用户不需要安装 Python，也不需要打开终端或 PowerShell。下载 App/EXE，
打开后点一下安装即可。

## 一键安装

安装前先确认：

1. Claude Science 至少打开过一次，然后可以先关掉。
2. ccswitch 或 Claude Code 里已经选好了你想用的模型。

### macOS

1. 下载：
   [ccscience-sync-macos.zip](https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-macos.zip)
2. 解压 ZIP。
3. 打开 `ccscience-sync.app`。
4. 点击 `Install / Update`。

如果 macOS 拦截应用，请右键点击 App，选择 `Open`，再确认打开。

### Windows

1. 下载：
   [ccscience-sync-windows.zip](https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-windows.zip)
2. 解压 ZIP。
3. 打开 `ccscience-sync.exe`。
4. 点击 `Install / Update`。

如果出现 Windows SmartScreen 提示，选择 `More info`，再点 `Run anyway`。

## 怎么判断成功了

在 App 里点击 `Check Status`。

看到类似下面两行，就说明成功：

```text
helper: running (...)
runtime patch: installed (...)
```

之后正常使用 ccswitch 或 Claude Code 切模型即可。你新建 Claude Science
会话时，它会自动使用同步过来的模型。

## 平时怎么用

安装完成后，不需要一直开着这个 App。

1. 在 ccswitch 或 Claude Code 里切换模型。
2. 新建 Claude Science 会话。
3. Claude Science 会自动使用同步后的模型。

如果 Claude Science 更新了，再打开 `ccscience-sync`，点击 `Install / Update`。

## 卸载

打开 `ccscience-sync`，点击 `Uninstall`。

## 常见问题

### 提示找不到 Claude Science runtime

先打开一次 Claude Science，再关闭，然后重新点击 `Install / Update`。

### 模型没有立刻变化

请新建一个 Claude Science 会话。已经打开的旧会话可能会继续使用创建时的模型。

### 系统提示应用有风险或无法验证

当前版本还没有做商业代码签名。macOS 和 Windows 可能会提示安全警告。
这是小型开源工具常见的情况，不代表程序会读取或上传你的密钥。

## 这个工具做了什么

`ccscience-sync` 是一个本地辅助工具。它会读取
`~/.claude/settings.json` 里的当前模型，把它转换成 Claude Science 使用的
模型 ID，然后在本机把 Claude Science 新会话的模型同步过去。

它不会读取、保存、打印、上传或在文档中记录 API key、密码、token 或其他凭据。

## 从源码运行

如果你是开发者，或者不想使用打包好的 App/EXE，可以安装 Python 3.9 或更新版本，
然后运行：

```sh
git clone https://github.com/Qinbf/ccscience-sync.git
cd ccscience-sync
python3 ccscience_sync.py
```

常用命令：

```sh
python3 ccscience_sync.py install
python3 ccscience_sync.py status
python3 ccscience_sync.py uninstall
```

Windows：

```powershell
py -3 .\ccscience_sync.py install
py -3 .\ccscience_sync.py status
py -3 .\ccscience_sync.py uninstall
```

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
