# AreaDay 安装和使用指南

**适用版本：AreaDay v1.1.0**　｜　更新日期：2026-09-20

AreaDay 是运行在 Codex 或 WorkBuddy 中的研究辅助 Skill。它可以根据你的研究方向建立个人领域词表，并用于浏览词表、复习术语和生成研究简报。

> **推荐流程：先下载与你的电脑系统匹配的 AreaDay 安装包，再按照本指南操作。** 提前下载好安装包，并把压缩包的完整路径告诉 AI 助手，安装会更快、更稳定。

- GitHub 最新发布页：<https://github.com/vvJesse/AreaDay-Release/releases/latest>

## 一、下载安装包

只需要下载与你的电脑匹配的一个安装包：

### Apple 芯片 Mac（M1、M2、M3、M4 或更新型号）

- [直接下载 AreaDay 1.1.0 macOS 安装包](https://pub-5c1e2895a3f841ccbbb359ab9963e5ac.r2.dev/releases/1.1.0/AreaDay-macos-arm64-v1.1.0.zip)
- 文件名：`AreaDay-macos-arm64-v1.1.0.zip`

### 64 位 Windows（Intel 或 AMD 处理器）

- [直接下载 AreaDay 1.1.0 Windows 安装包](https://pub-5c1e2895a3f841ccbbb359ab9963e5ac.r2.dev/releases/1.1.0/AreaDay-windows-x64-v1.1.0.zip)
- 文件名：`AreaDay-windows-x64-v1.1.0.zip`

如果需要查看更新版本，可以打开 [GitHub 最新发布页](https://github.com/vvJesse/AreaDay-Release/releases/latest)，下载名称以 `AreaDay-macos-arm64-` 或 `AreaDay-windows-x64-` 开头的完整安装包。

注意：

- 暂不支持 Intel 芯片 Mac。
- 不要下载 GitHub 自动生成的 `Source code (zip)` 或 `Source code (tar.gz)`。
- 不要单独下载文件名中含有 `runtime` 的压缩包。
- 下载后不需要自己解压、安装 Python 或运行终端命令。

## 二、安装前准备

请准备好 Codex 或 WorkBuddy，以及刚刚下载的 AreaDay 安装包。

安装时，把 ZIP 文件直接作为附件上传，或把下载后的完整文件路径告诉 AI 助手。若助手提示需要访问本地文件或网络，请允许这次访问。

## 三、让 AI 助手完成安装

在 Codex 或 WorkBuddy 中新建任务，把下面这段文字粘贴到输入框，并将“安装包路径”替换为刚刚下载的 ZIP 完整路径：

```text
https://github.com/vvJesse/AreaDay-Release
帮我安装这个 Skill。
安装包路径：［下载好的 AreaDay 压缩包完整路径］
```

确认替换后的文字无误，再点击“发送”。等待 AI 助手完成安装，看到 `Installation verified` 就表示安装完成。

如果安装后暂时识别不到 AreaDay，请重启 Codex 或 WorkBuddy，或新建一个任务后再调用。

## 四、配置 OpenAlex API Key

AreaDay 会使用 OpenAlex 检索论文。OpenAlex API Key 是免费的访问密钥；安装后和首次建立词表前，AreaDay 都会检查是否已经配置。

如果还没有 Key：

1. 打开 [OpenAlex API Key 页面](https://openalex.org/settings/api)。
2. 登录 OpenAlex；如果还没有账号，按页面提示免费注册。
3. 复制页面中的 API Key。
4. 回到 Codex 或 WorkBuddy，告诉 AI 助手“帮我配置 OpenAlex API Key”。助手会打开配置位置；把 Key 填到 `api_key =` 后面，保存即可。

不要把 API Key 发到聊天框，也不要粘贴到任何在线工具。如果已经配置过，直接继续下一步即可。

## 五、调用 AreaDay

不同 AI 助手的 Skill 调用格式可能不同：

- WorkBuddy 通常使用 `/areaday`
- Codex 等环境通常使用 `$areaday`

如果一种写法无法识别，就换另一种；也可以直接说“请使用 AreaDay 完成以下任务”。

## 六、首次建立个人领域词表

新建任务后发送：

```text
/areaday 首次建立我的研究领域和个人词表。
我的研究方向是：［说明具体课题、关注的问题和研究对象］
```

如果使用 Codex，可以把 `/areaday` 改为 `$areaday`。

接下来按 AI 助手的提问操作即可：

1. 确认研究范围和词表保存位置。
2. 如果尚未配置 OpenAlex API Key，按上一节的说明完成配置。
3. 等待 AreaDay 检索论文并准备词表；任务运行期间不要关闭 Codex 或 WorkBuddy。
4. 校准页面打开后，完成单词识别题。答题结束后，AreaDay 会生成个人领域词表并打开工作台。

答题时只判断自己是否理解该词最常见的含义，不要查词典；不确定时选择“不确定”。

## 七、日常使用

### 打开工作台

```text
/areaday 打开工作台。
```

工作台可用于查看个人领域词表、复习术语、阅读研究简报，以及切换不同研究领域。

### 立即生成研究简报

```text
/areaday 为［研究领域名称］生成一份研究简报。
```

### 设置每周研究简报

```text
/areaday 每周一上午 9 点为［研究领域名称］生成研究简报。
```

### 设置每日复习提醒

```text
/areaday 每天晚上 8 点检查到期词汇；有需要复习的内容时再提醒我。
```

使用 Codex 时，可以把以上命令中的 `/areaday` 改为 `$areaday`。

## 八、常见问题

**安装后找不到 AreaDay**  
重启 Codex 或 WorkBuddy，或新建任务后再次调用。`/areaday` 无法识别时，改用 `$areaday`。

**AI 助手不知道安装包在哪里**  
把 ZIP 直接作为附件上传，或提供下载后文件的完整路径。不要只说“在下载目录里”。

**校准页面无法加载**  
先刷新页面；仍无法打开时，让 AI 助手“重新打开 AreaDay 校准页面”。

**工作台显示服务已关闭**  
回到 Codex 或 WorkBuddy，发送“`/areaday` 打开工作台”。

**没有找到足够的论文**  
提供一个包含相关 PDF 的本地文件夹，让 AreaDay 使用这些论文继续建立词表。

## 九、数据与隐私

论文、提取后的文本、词表、简报和学习记录保存在本地。词表校准完全在本地完成：生成个人词表所需的单词统计信息和单词识别答案只在你的电脑上使用，不会发送到任何服务器，论文原文、PDF、来源网址和本地文件路径也不会外传。

研究资料和学习记录会保存在本地。
