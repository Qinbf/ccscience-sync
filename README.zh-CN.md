# ccscience-sync

[English](README.md) | [中文](README.zh-CN.md)

**让 Claude Science 用上你在 CC.Switch 里选的任意模型。** 装一次，之后随便切，不用重装。

一个很小的桌面小工具：**不用装 Python、不用开终端**，下载、打开、点一下就好。

需要按截图操作，可以看 [中文图文说明](docs/USER_GUIDE.zh-CN.md) 或
[English quick guide](docs/USER_GUIDE.md)。

## 它能做什么

Claude Science 默认只能用官方 Claude。装上本工具后，它会跟着你**在 CC.Switch 里选的模型**走：

- **官方 Claude** —— Opus、Sonnet、Haiku。
- **第三方模型** —— DeepSeek、Kimi（Moonshot）、GLM（智谱）、MiniMax 等。
  本工具会自动把每家服务商的接口格式转换好，让它们直接可用。

在 CC.Switch 里选个模型 → 新开一个 Claude Science 会话 → 它就用那个模型。
**装一次即可，之后切模型永远不用重装。**

## 安装（三步）

开始前：Claude Science 至少打开过一次（然后可以关掉）；CC.Switch 里已经选好想用的模型。

**macOS**
1. 下载 [ccscience-sync-macos.zip](https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-macos.zip) 并解压
2. 打开 `ccscience-sync.app`
3. 点 **「① 一键安装 / 更新」** —— 完成 ✅

> 首次打开被系统拦？属正常（本工具免费、未做付费签名）：较新的 macOS 打开
> `系统设置 › 隐私与安全性`，往下找到本应用点 `仍要打开`；旧版可右键 App → `打开`。
> 更多情况见 [docs/INSTALL.md](docs/INSTALL.md)。

**Windows**
1. 下载 [ccscience-sync-windows.zip](https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-windows.zip) 并解压
2. 打开 `ccscience-sync.exe`
3. 点 **「① 一键安装 / 更新」** —— 完成 ✅

> 出现 SmartScreen 提示 → 点 `更多信息` → `仍要运行`。

## 平时怎么用

1. 在 **CC.Switch** 里切换模型
2. 在本工具里点 **「打开 Claude Science」**
3. 新会话自动用上你刚选的模型 —— 不用重装、不用改任何设置

想确认装好了没：点 **「检查状态」**，看到下面两行就 OK：

```text
后台服务：运行中 (...)
运行时补丁：已安装 (...)
```

**只有一种情况需要再点一次「一键安装 / 更新」**：Claude Science 自己升级到了新版本
（这时「检查状态」会显示 `运行时补丁：未安装`）。平时切模型完全不用管。

## 没有 Claude 账号？用「第三方免登录」

只有当你**没有任何 Claude 账号**、但有第三方模型 API（如 DeepSeek、MiniMax）时才需要。
**有 Claude 账号就跳过本节。**

1. 在 CC.Switch 里选一个第三方模型
2. 在本工具里点 **「第三方免登录」**
3. Claude Science 直接可用 —— 不需要账号，也没有登录界面

它会启动一个**独立、隔离**的 Claude Science（自己的目录和端口，**绝不触碰**你真实的登录），
把请求经过本工具**内置的本地转发器**直连你自己的第三方 API。你的 Key 始终留在本机。
想停掉，点 `卸载` 即可。

## 常见问题

**Claude Science 要我登录？** 本地链接是一次性的、会过期。点 **「打开 Claude Science」**
生成新链接即可。用的是你真实的 Claude 账号，不绕过登录。完全没有账号，请改用上面的「第三方免登录」。

**提示找不到 Claude Science runtime？** 先打开一次 Claude Science 再关掉，然后重新点
「一键安装 / 更新」。

**模型没有立刻变化？** 请**新建**一个会话；已经开着的旧会话会继续用创建时的模型。切模型不用重装。

**系统提示应用有风险 / 无法验证？** 当前版本没有做商业代码签名，macOS / Windows 会有安全警告，
这是小型开源工具的常见情况，按上面提示放行即可。它不会读取或上传你的任何密钥。

## 卸载

打开本工具，点 **「卸载」**。

## 名词说明（避免混淆）

- **CC.Switch（cc-switch）** —— 你**用来切模型 / 配第三方 API** 的那个软件，决定
  Claude Code / Claude Science 用哪个模型。**这是本工具唯一需要配合的对象。**
- **Claude Science** —— 被本工具改变模型来源的那个应用。

## 从源码运行（开发者）

```sh
git clone https://github.com/Qinbf/ccscience-sync.git
cd ccscience-sync
python3 ccscience_sync.py            # 打开图形界面
python3 ccscience_sync.py install    # 或用命令行安装
python3 ccscience_sync.py status     # 查看状态
python3 ccscience_sync.py uninstall  # 卸载
```

Windows 把 `python3` 换成 `py -3`。

## 自定义模型映射（可选）

本工具会把 CC.Switch 里的模型名映射成 Claude Science 的模型 ID。默认映射：

| 源模型包含 | Claude Science 模型 |
| --- | --- |
| `opus` | `claude-opus-4-8` |
| `sonnet` | `claude-sonnet-5` |
| `sonnet-4`、`4.6` | `claude-sonnet-4-6` |
| `haiku` | `claude-haiku-4-5` |
| `fable` | `claude-fable-5` |

想自定义，创建 `~/.ccscience-sync.json`：

```json
{
  "model_map": {
    "opus[1m]": "claude-opus-4-8",
    "sonnet[1m]": "claude-sonnet-5"
  }
}
```

## 许可证

MIT
