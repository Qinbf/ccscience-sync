<div align="center">

<img src="assets/icon.png" alt="ccscience" width="112" height="112">

# ccscience

**让 Claude Science 直接用上你在 CC.Switch 里选的模型。**

[English](README.md) · [中文](README.zh-CN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
&nbsp;![Platform](https://img.shields.io/badge/macOS%20·%20Windows-informational)
&nbsp;[![下载](https://img.shields.io/badge/下载-Releases-brightgreen)](https://github.com/Qinbf/ccscience/releases/latest)

</div>

在 CC.Switch 里切模型，新开一个 Claude Science 会话即可——就这么简单。
只需安装一次，之后切模型都不用重装。

<div align="center">
<img src="docs/images/user-guide-01-main.png" alt="ccscience 主界面" width="760">
</div>

## 能做什么

- ✅ **官方 Claude 模型**——Opus、Sonnet、Haiku 等
- 🔌 **第三方模型**——DeepSeek、Kimi、GLM、MiniMax 等
- 🔓 **没有 Claude 账号也能用**——用你自己的第三方 API 打开本地免登录版 Claude Science

## 开始前

ccscience 要配合另外两个 App 一起用——先把它们准备好：

- **[CC.Switch](https://github.com/SuperJJ007/CSSwitch)**——你在这里挑模型（官方 Claude，或 DeepSeek、Kimi、GLM、MiniMax 等第三方 API）。装好并选一个模型。
- **Claude Science**——ccscience 要给它打补丁的 App，先打开一次，让它的文件落到本机。

## 三步开始

**1 · 下载并打开软件**

到 **[Releases](https://github.com/Qinbf/ccscience/releases/latest)** 下载最新版 macOS 或 Windows 构建，解压后打开。

**2 · 点击「① 一键安装 / 更新」，再点「检查状态」**

看到下面两项就说明可以用了：

```text
后台服务：运行中
运行时补丁：已安装
```

只有当 *Claude Science 自己升级* 后才需要再点一次——平时切模型不用重装。

**3 · 启动 Claude Science** ——按下面选你的路线 ⤵

## 路线 A · 有 Claude 账号

1. 在 CC.Switch 里切到目标模型
2. 点击 **「打开 Claude Science」**
3. 新建一个会话

如果页面要求登录，正常登录即可。打开的链接会过期，过期后回到本软件重新点「打开 Claude Science」。

<div align="center">
<img src="docs/images/user-guide-03-web-dashboard.png" alt="Claude Science 项目页" width="760">
</div>

## 路线 B · 没有 Claude 账号

有第三方 API、但没有 Claude 账号？用免登录模式：

1. 在 CC.Switch 里选择第三方模型
2. 点击 **「第三方免登录」**
3. 浏览器会打开本地 Claude Science 页面

它运行在**隔离的本地沙箱**里，不会碰你真实的 Claude 登录态。请求通过本机转发器发到你选择的第三方 API。密钥只从本地配置或环境变量读取——绝不写进代码或文档。

## 开始对话

打开或新建一个项目，点击左侧 **「New」**，输入你的问题。输入框底部会显示当前模型：

<div align="center">
<img src="docs/images/user-guide-04-composer.png" alt="输入框与模型选择" width="560">
</div>

> **模型没变？** 旧会话会保留创建时的模型。切换后请务必**新建**会话。

## 常见问题

<details>
<summary><b>点击展开常见处理</b></summary>

- **模型没变**——旧会话会保留创建时的模型，请新建会话。
- **页面打不开**——点「检查状态」，确认后台服务、第三方转发器、免登录沙箱都在运行；旧链接过期时重新点入口按钮。
- **找不到 runtime**——先手动打开一次 Claude Science，再点「① 一键安装 / 更新」。
- **出现 `Agent Failed` / `invalid params`**——更新到最新版，重新点「第三方免登录」打开新页面，再新建会话测试。

</details>

## 卸载

打开本软件，点击 **「卸载」**。

## 从源码运行

```sh
git clone https://github.com/Qinbf/ccscience.git
cd ccscience
python3 ccscience.py
```

Windows 把 `python3` 换成 `py -3`。

## 许可证

[MIT](LICENSE)
