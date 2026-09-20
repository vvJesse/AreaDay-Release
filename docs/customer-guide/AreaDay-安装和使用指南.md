# AreaDay 安装和使用指南

**适用版本：AreaDay v1.1.0**　｜　更新日期：2026-09-16

AreaDay 是运行在 Codex 或 WorkBuddy 中的研究辅助 Skill。它可以根据你的研究方向建立个人领域词表，并用于浏览词表、复习术语和生成研究简报。

> **推荐流程：先下载与你的电脑系统匹配的 AreaDay 安装包，再按照本指南或视频教程操作。** 提前下载好安装包，并把压缩包的完整路径告诉 AI 助手，安装会更快、更稳定。

- 视频教程：<https://guide.areaday.app/>
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

请准备好：

- Codex 或 WorkBuddy
- 下载好的 AreaDay 安装压缩包
- 可以联网的电脑（下载依赖时需要联网）

为了让 AI 助手快速找到安装包，请提供下载后 ZIP 文件的完整路径，例如：

```text
/Users/你的名字/Downloads/AreaDay-macos-arm64-v1.1.0.zip
```

Windows 路径可能类似：

```text
C:\Users\你的名字\Downloads\AreaDay-windows-x64-v1.1.0.zip
```

### AI 助手会请求的权限

AreaDay 完全在你自己的电脑上运行，但有几件事需要你授权，助手会在开始前一次性向你申请：

- **联网**：向 OpenAlex 检索论文元数据、下载论文全文（全文也可能来自论文所在的出版社或机构仓库网址）；只有在选择 arXiv 时才会访问 arXiv。
- **写入本机目录**：领域注册表与复习状态存放在系统应用数据目录（macOS 为 `~/Library/Application Support/AreaDay/data`），OpenAlex 配置存放在 `~/.areaday/credentials.ini`，词向量模型存放在 `~/.areaday/models`，运行环境装在本 Skill 目录内；建立词表与生成简报时还会写入你确认的工作区目录。
- **本机端口（打开工作台时）**：工作台会在本机 `127.0.0.1` 启动一个只对本机开放的小型服务（优先 8765 端口），再用浏览器打开页面。若你的助手默认禁止访问本机端口，打开工作台这一步会失败，需要为它放开权限。
- **系统计划任务（仅当你设置每周简报或每日复习提醒时）**：由助手在你的系统里创建定时任务。

如果你不愿意授予某项权限，助手会告诉你哪一步会受影响，而不是安静地降级处理。

## 三、让 AI 助手完成安装

在 Codex 或 WorkBuddy 中新建任务，把下面这段文字粘贴到输入框，并将“安装包路径”替换为刚刚下载的 ZIP 完整路径：

```text
https://github.com/vvJesse/AreaDay-Release
帮我安装这个 Skill。
安装包路径：［下载好的 AreaDay 压缩包完整路径］
```

确认替换后的文字无误，再点击“发送”。安装不需要许可证、激活码或账号，也不需要额外上传任何凭据文件。

AI 助手会完成以下工作：

1. 检查安装包是否与当前系统匹配。
2. 安装 AreaDay 及其自带的运行环境。
3. 运行安装自检，确认依赖和本地模型可用。

看到 `Installation verified`，表示 AreaDay 已经安装完成。安装过程不需要激活码，也不限制设备数量。

如果安装后暂时识别不到 AreaDay，请重启 Codex 或 WorkBuddy，或新建一个任务后再调用。

> WorkBuddy 用户：安装或计划任务偶尔会受沙箱限制。如果 AI 助手明确提示权限被拦截，可以在确认信任 AreaDay 后暂时关闭沙箱；任务完成后重新开启。Codex 通常不需要调整此项。

## 四、调用 AreaDay

不同 AI 助手的 Skill 调用格式可能不同：

- WorkBuddy 通常使用 `/areaday`
- Codex 等环境通常使用 `$areaday`

如果一种写法无法识别，就换另一种；也可以直接说“请使用 AreaDay 完成以下任务”。

## 五、首次建立个人领域词表

新建任务后发送：

```text
/areaday 首次建立我的研究领域和个人词表。
我的研究方向是：［说明具体课题、关注的问题和研究对象］
```

如果使用 Codex，可以把 `/areaday` 改为 `$areaday`。

接下来：

1. 根据 AI 助手的提问，确认研究范围和本地保存位置。
2. 确认后，AreaDay 会准备检索论文。检索需要你自己的 OpenAlex API Key（免费）。如果还没配置，AreaDay 会让你运行一条命令：

   ```text
   .venv/bin/python scripts/configure_openalex.py
   ```

3. 这条命令会把配置文件 `~/.areaday/credentials.ini` 打开在你的文本编辑器里，然后立刻结束——不会有任何程序在等你输入。到 https://openalex.org/settings/api 登录或免费注册，复制完整 Key，粘贴到文件里 `api_key =` 的后面，保存文件，然后回到对话告诉 Agent「填好了，继续」，它会自动验证并接着往下做。
   不要把 Key 发到聊天框，也不要粘贴到任何在线工具。想随时确认当前有没有配置好，可以运行 `.venv/bin/python scripts/configure_openalex.py --check`。
4. AreaDay 开始检索论文、分析语料并准备词表。这个过程可能需要一段时间；不要关闭正在执行任务的 Codex 或 WorkBuddy。
5. 校准页面打开后，完成 30 道单词识别题。
6. 答题结束后，AreaDay 会生成个人领域词表并打开工作台。

答题时只判断自己是否理解该词最常见的含义，不要查词典；不确定时选择“不确定”。

## 六、日常使用

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

## 七、常见问题

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

## 八、数据与隐私

论文、提取后的文本、词表、简报和学习记录保存在本地。词表校准完全在本地完成：生成个人词表所需的单词统计信息和单词识别答案只在你的电脑上使用，不会发送到任何服务器，论文原文、PDF、来源网址和本地文件路径也不会外传。
