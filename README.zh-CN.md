# ccscience-sync

[English](README.md) | [中文](README.zh-CN.md)

让 Claude Science 自动使用你在 ccswitch / Claude Code / CSSwitch 里选择的模型；
如果你没有 Claude 订阅，还能**不登录**、完全用你自己的第三方模型 API 来跑
Claude Science。

普通用户不需要安装 Python，也不需要打开终端或 PowerShell。下载 App/EXE，
打开后点一下安装即可。

桌面 App 会自动检测系统语言：中文系统显示中文，其他系统默认显示英文。

打开 Claude Science 有两种方式：

- **`打开 Claude Science`**——真实实例，用你的 Claude 账号。它同步你选好的模型
  并打开一次性链接，不绕过登录。
- **`第三方免登录`**——一个隔离的本地实例，使用本机生成的虚拟登录，完全经由
  CSSwitch 代理跑在你自己的第三方模型 API 上。它绝不触碰你真实的 Claude 账号或
  `~/.claude-science`。

## 一键安装

安装前先确认：

1. Claude Science 至少打开过一次，然后可以先关掉。
2. ccswitch、Claude Code 或 CSSwitch 里已经选好了你想用的模型。

### macOS

1. 下载：
   [ccscience-sync-macos.zip](https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-macos.zip)
2. 解压 ZIP。
3. 打开 `ccscience-sync.app`。
4. 点击 `一键安装 / 更新`。
5. 需要打开 Claude Science 时，点击 `打开 Claude Science` 获取新鲜链接。

如果 macOS 拦截应用：旧版 macOS 可右键点击 App，选择 `打开`，再确认；较新的
macOS（15 Sequoia 及以上，右键已不能绕过未签名应用）请打开 `系统设置 › 隐私与
安全性`，往下拉找到本应用，点 `仍要打开`。如果仍提示应用“已损坏”或无法打开，
是下载被系统加了隔离标记：打开“终端”，运行
`xattr -dr com.apple.quarantine /路径/ccscience-sync.app`（先输入命令和一个空格，
再把 App 拖到终端窗口即可自动补全路径），然后重新打开。本工具免费、未做付费签名，
这些只是第一次打开时的一次性步骤，不是病毒警告。

### Windows

1. 下载：
   [ccscience-sync-windows.zip](https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-windows.zip)
2. 解压 ZIP。
3. 打开 `ccscience-sync.exe`。
4. 点击 `一键安装 / 更新`。
5. 需要打开 Claude Science 时，点击 `打开 Claude Science` 获取新鲜链接。

如果出现 Windows SmartScreen 提示，选择 `More info`，再点 `Run anyway`。

## 怎么判断成功了

在 App 里点击 `检查状态`。

看到类似下面两行，就说明成功：

```text
后台服务：运行中 (...)
运行时补丁：已安装 (...)
```

如果你使用 CSSwitch 的第三方模型，还应该看到：

```text
CSSSwitch 代理：运行中 (http://127.0.0.1:18991/****)
CSSSwitch 模型：...
```

之后正常使用 ccswitch 或 Claude Code 切模型即可。你新建 Claude Science
会话时，它会自动使用同步过来的模型。

## 平时怎么用

安装完成后，不需要一直开着这个 App。

1. 在 ccswitch 或 Claude Code 里切换模型。
2. 新建 Claude Science 会话。
3. Claude Science 会自动使用同步后的模型。

如果你用的是 CSSwitch 第三方模型：

1. 先在 CSSwitch 里选择第三方配置，并让它的本地代理保持运行。
2. 在 `ccscience-sync` 里点击 `打开 Claude Science`。
3. 如果 Claude Science 要求登录，请正常登录；登录后推理请求会走 CSSwitch 的本地代理。

ccswitch 或 Claude Code 里切换模型后，不需要重装 `ccscience-sync`。新建
Claude Science 会话时，它会自动读取最新模型。

只有 Claude Science 本身更新了，或者状态里没有看到
`运行时补丁：已安装`，才需要再次点击 `一键安装 / 更新`。

## 第三方免登录模式

适合：没有 Claude 订阅，但有第三方模型 API Key（通过 CSSwitch）的用户。

1. 在 CSSwitch 里选择一个第三方配置，并让它的本地代理保持运行。
2. 在 `ccscience-sync` 里点击 `第三方免登录`。
3. Claude Science 直接打开可用——不需要 Claude 账号，也没有登录界面。

它具体做了什么：

- 启动一个**独立、隔离**的 Claude Science 实例（自己的 HOME、数据目录和端口，
  绝不使用真实端口 8765），并生成一个**本机虚拟登录**
  （`virtual@localhost.invalid`），让 Claude Science 无需 Claude 账号即可启动。
- 所有推理都经由你的 CSSwitch 本地代理——代理会剥掉这个虚拟凭证，换成你自己的
  第三方 API Key 发给你选择的模型。
- 它**绝不读取、复制、修改或删除**你真实的 `~/.claude-science` 或真实 Claude
  登录。硬性护栏会拒绝在真实端口或真实凭证目录上运行。

这**不是**绕过 Anthropic 服务器上的账号鉴权：推理根本不会到达 Anthropic。虚拟
登录只是让本地的 Claude Science 程序能启动，从而去访问你的第三方模型。

前提：CSSwitch 必须在运行，已选好第三方配置，且本地代理健康。如果没有，
`ccscience-sync` 会提示你并且什么都不做。

想停掉这个隔离实例，运行 `stop-thirdparty`（或点击 `卸载`）。

## 卸载

打开 `ccscience-sync`，点击 `卸载`。

## 常见问题

### Claude Science 要我登录

Claude Science 的本地浏览器链接是一次性链接，会过期。打开 `ccscience-sync`，
点击 `打开 Claude Science`，它会自动生成并打开一个新的本地链接。

如果 Claude Science 要求登录 Claude 账号，请正常登录。`打开 Claude Science`
使用你真实的 Claude 账号，不绕过这个登录。

如果你没有 Claude 账号，请改用 `第三方免登录`：它会启动一个独立隔离的实例，
跑在你自己的第三方模型 API 上。详见 [第三方免登录模式](#第三方免登录模式)。

### 提示找不到 Claude Science runtime

先打开一次 Claude Science，再关闭，然后重新点击 `一键安装 / 更新`。

### 模型没有立刻变化

请新建一个 Claude Science 会话。已经打开的旧会话可能会继续使用创建时的模型。

ccswitch 或 Claude Code 切换模型后，不需要重装 `ccscience-sync`。

### 系统提示应用有风险或无法验证

当前版本还没有做商业代码签名。macOS 和 Windows 可能会提示安全警告。
这是小型开源工具常见的情况，不代表程序会读取或上传你的密钥。

## 这个工具做了什么

`ccscience-sync` 是一个本地辅助工具。它会读取
`~/.claude/settings.json` 里的当前模型，把它转换成 Claude Science 使用的
模型 ID，然后在本机把 Claude Science 新会话的模型同步过去。

如果检测到 `~/.csswitch/config.json` 里有正在使用的 CSSwitch 第三方 profile，
并且 CSSwitch 的本地代理正在运行，`打开 Claude Science` 会给
`claude-science` 进程设置 `ANTHROPIC_BASE_URL`，让 Claude Science 的推理请求
走 CSSwitch 代理。代理地址里的 secret 只用于本机连接，不会打印明文。

它不是固定每 5 秒傻刷。Claude Science 页面重新变为活跃、用户点击或按键、
以及新建会话请求发出前，都会刷新一次最新模型。

它不会保存、打印、上传或在文档中记录 API key、密码、token 或其他凭据。
桥接 CSSwitch 时，它只使用 profile 名称、模型、端口和本地代理 secret，不使用
CSSwitch 配置里的 API key 字段。

`第三方免登录` 会在一个隔离的沙箱目录里生成本机虚拟登录，并启动一个独立的
`claude-science` 实例，把推理导向 CSSwitch 代理。虚拟 token 里的凭证是个会被代理
丢弃的占位值；你真正的第三方 API Key 始终留在 CSSwitch 里。沙箱绝不触碰真实的
`~/.claude-science`，护栏会拒绝真实端口和真实凭证目录。

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
python3 ccscience_sync.py open-thirdparty   # 隔离的第三方免登录实例
python3 ccscience_sync.py stop-thirdparty
python3 ccscience_sync.py uninstall
```

Windows：

```powershell
py -3 .\ccscience_sync.py install
py -3 .\ccscience_sync.py status
py -3 .\ccscience_sync.py open-thirdparty
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
