# ccscience

[English](README.md) | [中文](README.zh-CN.md)

**让 Claude Science 使用你在 CC.Switch 里选择的模型。**

安装一次即可。之后在 CC.Switch 里切模型，新开 Claude Science 会话就会自动使用新模型，不需要反复安装。

## 支持什么

- 官方 Claude：Opus、Sonnet、Haiku 等
- 第三方模型：DeepSeek、Kimi、GLM、MiniMax 等
- 无 Claude 账号时，也可以用第三方 API 打开本地免登录版 Claude Science

## 安装

先准备好两件事：

1. Claude Science 至少打开过一次
2. CC.Switch 里已经选好要用的模型

然后下载并打开本工具：

- macOS：到 [GitHub Releases](https://github.com/Qinbf/ccscience-sync/releases/latest) 下载最新版 macOS 构建
- Windows：到 [GitHub Releases](https://github.com/Qinbf/ccscience-sync/releases/latest) 下载最新版 Windows 构建

打开后点击 **「① 一键安装 / 更新」**。

<img src="docs/images/user-guide-01-main.png" alt="ccscience 主界面" width="720">

安装完成后，点击 **「检查状态」**。看到下面两项就说明可以用了：

```text
后台服务：运行中
运行时补丁：已安装
```

只有 Claude Science 自己升级后，才需要再次点击 **「① 一键安装 / 更新」**。平时切模型不用重装。

## 有 Claude 账号时

1. 在 CC.Switch 里切到目标模型
2. 点击 **「打开 Claude Science」**
3. 在 Claude Science 里新建会话

如果页面要求登录，正常登录即可。打开链接会过期，过期后回到本工具重新点击 **「打开 Claude Science」**。

## 没有 Claude 账号时

如果你没有 Claude 账号，但有第三方模型 API：

1. 在 CC.Switch 里选择第三方模型
2. 点击 **「第三方免登录」**
3. 浏览器会打开本地 Claude Science 页面

<img src="docs/images/user-guide-03-web-dashboard.png" alt="第三方免登录页面" width="720">

这个页面是隔离的本地沙箱，不会使用你的真实 Claude 登录态。请求会通过本机转发器发到你选择的第三方 API。密钥只从你的本地配置或环境变量读取，不要写进代码或文档。

## 开始对话

打开或新建项目，点击左侧 **New**。输入框底部会显示当前模型：

<img src="docs/images/user-guide-04-composer.png" alt="输入框与模型选择" width="520">

输入问题并发送即可。第一次使用工具时，如果页面弹出授权提示，只允许你信任的工具。

## 常见问题

**模型没变？** 旧会话会保留创建时的模型。切换模型后，请新建会话测试。

**页面打不开？** 点击 **「检查状态」**，确认后台服务、第三方转发器和免登录沙箱都在运行。旧链接过期时，重新点击入口按钮。

**提示找不到 Claude Science runtime？** 先手动打开一次 Claude Science，再回到本工具点击 **「① 一键安装 / 更新」**。

**出现 `Agent Failed` / `invalid params`？** 确认使用最新版，重新点击 **「第三方免登录」** 打开新页面，再新建会话测试。

## 卸载

打开本工具，点击 **「卸载」**。

## 从源码运行

```sh
git clone https://github.com/Qinbf/ccscience-sync.git ccscience
cd ccscience
python3 ccscience_sync.py
```

Windows 把 `python3` 换成 `py -3`。

## 许可证

MIT
