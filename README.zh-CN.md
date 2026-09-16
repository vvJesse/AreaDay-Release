# AreaDay

[English](README.md) | [简体中文](README.zh-CN.md)

AreaDay 以独立 Skill 的形式提供，支持 Codex 和 WorkBuddy。
它完全离线运行，不需要许可证、激活码或账号。

#### WorkBuddy 用户须知

本 Skill 已使用 **DeepSeek-V4-Flash** 在 **WorkBuddy** 上完成全流程测试，
其他兼容模型也可能正常工作。

WorkBuddy 的沙箱会限制完整流程所需的部分系统级操作。例如，`schtasks`
可能会被拦截，导致计划任务无法完成。

目前，我们尚未找到一种既保留全部沙箱限制，又足够可靠、易用的解决方案。
对于受影响的步骤，**暂时关闭 WorkBuddy 沙箱是目前最可靠的应对方式**。

关闭沙箱会降低 WorkBuddy 提供的安全隔离，使 Agent 可能访问你的账户有权访问的
文件和系统资源。请仅在你信任本 Skill 和当前任务时执行，不要以管理员身份运行
WorkBuddy，并在任务完成后**重新启用沙箱**。

如果你不愿暂时关闭沙箱，请在**购买前**考虑这一限制。目前，我们无法保证
在始终启用沙箱的情况下完整流程能够正常运行。

## 安装

建议先从[最新版本](https://github.com/vvJesse/AreaDay-Release/releases/latest)
下载与电脑系统匹配的完整安装 ZIP。然后在 Codex 或 WorkBuddy 中发送发布仓库链接、
“帮我安装这个 Skill。”以及本地 ZIP 的完整路径后发送即可，无需激活码或凭据文件。

完整步骤、安装包直链和首次使用说明见
[AreaDay 安装和使用指南](docs/customer-guide/AreaDay-安装和使用指南.md)。
Agent 必须阅读 [INSTALL.md](INSTALL.md)，完成安装和验证。用户无需自行解压
ZIP、移动文件夹、运行终端命令或安装依赖。

目前支持的发布平台：

- Intel 或 AMD 处理器的 64 位 Windows
- Apple 芯片 Mac（M1 或更新型号）

目前不支持 Intel 芯片 Mac。

## 安全与隐私

- 论文、PDF、提取后的文本、笔记、用户画像和词表数据均保存在用户电脑上。
  AreaDay 不会将论文原文或本地文件路径上传到任何地方。文本分词、嵌入推理以及
  30 题词汇校准全部在 Skill 内部本地运行，并明确关闭了 ONNX Runtime 遥测。
- 为查找论文，AreaDay 会向已启用的服务提供商发送搜索请求及相关元数据，目前包括
  OpenAlex，以及用户选择时使用的 arXiv。相应请求受这些服务提供商的条款和隐私
  政策约束。
- AreaDay 没有自己的服务器，不需要许可证、激活密钥、设备标识或账号，也不限制
  设备数量。
- OpenAlex API 密钥属于凭据。请妥善保管，不要将其
  提交到公共仓库，也不要粘贴到公开 Issue、提示词或其他公开位置。AreaDay 不需要
  访问你的其他文件。
- AreaDay 是研究与词汇辅助工具。在将生成结果用于研究或其他专业工作前，请自行
  检查确认。
