# ccscience-sync

[English](README.md) | [中文](README.zh-CN.md)

**让 Claude Science 用上你在 CC.Switch 里选的任意模型。装一次，之后随便切，不用重装。**

一个很小的桌面小工具：**不用装 Python、不用开终端**，下载、打开、点一下「一键安装」就好。

## 它能做什么

- ✅ **支持 CC.Switch 能用的所有模型** —— 官方 Claude，以及 CC.Switch 能配置的各种第三方中转（DeepSeek、Kimi、GLM、MiniMax 等）。你在 CC.Switch 里选哪个，Claude Science 就用哪个。
- ✅ **装一次，永久用** —— 之后在 CC.Switch 切模型，只要新开一个 Claude Science 会话就自动跟着变，**不用重装、不用重新设置**。
- ✅ **零门槛** —— 免 Python、免终端，双击 App 点一下即可。中文系统自动显示中文。

## 三步开始

开始前：Claude Science 至少打开过一次（然后可以关掉）；CC.Switch 里已经选好你想用的模型。

### macOS

1. 下载 [ccscience-sync-macos.zip](https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-macos.zip) 并解压
2. 打开 `ccscience-sync.app`
3. 点 **「① 一键安装 / 更新」** —— 完成 ✅

> 首次打开被系统拦？属正常（本工具免费、未做付费签名）：较新的 macOS 打开
> `系统设置 › 隐私与安全性`，往下找到本应用点 `仍要打开`；旧版可右键 App → `打开`。
> 更多情况见 [docs/INSTALL.md](docs/INSTALL.md)。

### Windows

1. 下载 [ccscience-sync-windows.zip](https://github.com/Qinbf/ccscience-sync/releases/latest/download/ccscience-sync-windows.zip) 并解压
2. 打开 `ccscience-sync.exe`
3. 点 **「① 一键安装 / 更新」** —— 完成 ✅

> 出现 SmartScreen 提示 → 点 `更多信息` → `仍要运行`。

## 平时怎么用

1. 在 **CC.Switch** 里切换模型
2. 在本工具里点 **「打开 Claude Science」** 打开一个新会话
3. 新会话自动用上你刚选的模型 —— **不用重装、不用改任何设置**

想确认装好了没：点 **「检查状态」**，看到下面两行就 OK：

```text
后台服务：运行中 (...)
运行时补丁：已安装 (...)
```

**只有一种情况需要再点一次「一键安装 / 更新」**：Claude Science 自己升级到了新版本
（这时「检查状态」会显示`运行时补丁：未安装`）。平时切模型完全不用管。

## 名词说明（避免混淆）

- **CC.Switch（cc-switch）** —— 你**用来切模型 / 配第三方 API** 的那个软件，决定
  Claude Code / Claude Science 用哪个模型或服务商。**这是本工具唯一需要配合的对象。**

## 可选：没有 Claude 账号时的「第三方免登录」

只有当你**没有任何 Claude 账号**、但有第三方模型 API（如 DeepSeek、MiniMax）时才需要这个模式。
**有 Claude 账号就跳过本节。**

1. 在 CC.Switch 里选一个第三方模型（它会写好该服务商的接口地址 + 你的 API Key）
2. 在本工具里点 **「第三方免登录」**
3. Claude Science 直接可用 —— 不需要 Claude 账号，也没有登录界面

它会启动一个**独立、隔离**的 Claude Science（自己的目录和端口，**绝不触碰**你真实的
`~/.claude-science` 或真实登录），用本机生成的虚拟登录启动；推理经过**本工具内置、隐藏在后台的
本地转发器**（自动把请求规整成你第三方端点认的格式、带上你的 Key），直连你自己的第三方 API。
**不再需要任何额外软件。** 这**不是**绕过 Anthropic 的账号鉴权——推理根本不会到达 Anthropic，
虚拟登录只是让本地程序能启动。想停掉它，点 `卸载` 即可。

## 卸载

打开本工具，点 **「卸载」**。

## 常见问题

**Claude Science 要我登录？**
本地链接是一次性的、会过期。点 **「打开 Claude Science」** 生成新链接即可。用的是你真实的
Claude 账号，不绕过登录。完全没有账号，请改用上面的「第三方免登录」。

**提示找不到 Claude Science runtime？**
先打开一次 Claude Science 再关掉，然后重新点 **「一键安装 / 更新」**。

**模型没有立刻变化？**
请**新建**一个 Claude Science 会话；已经开着的旧会话会继续用创建时的模型。切模型不用重装。

**系统提示应用有风险 / 无法验证？**
当前版本没有做商业代码签名，macOS / Windows 会有安全警告，这是小型开源工具的常见情况，
按上面「三步开始」里的提示放行即可。它不会读取或上传你的任何密钥。

## 从源码运行（开发者）

```sh
git clone https://github.com/Qinbf/ccscience-sync.git
cd ccscience-sync
python3 ccscience_sync.py            # 打开图形界面
python3 ccscience_sync.py install    # 或用命令行：安装
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
