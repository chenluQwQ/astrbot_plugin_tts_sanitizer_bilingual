# TTS文本过滤插件 - 双语TTS扩展版

基于 [柯尔](https://github.com/Luna-channel) 的 [astrbot_plugin_tts_sanitizer](https://github.com/Luna-channel/astrbot_plugin_tts_sanitizer) 修改，新增双语TTS、语音Tool、MiniMax停顿标记等功能。

原插件通过透明包装 TTS Provider 过滤不适合语音朗读的内容（颜文字、特殊符号、网络用语等），不修改消息链，不产生额外消息。详细说明请参阅原项目。

## ✨ 功能一览

| 功能 | 说明 | 需要配置 |
|------|------|----------|
| 文字过滤 | 过滤颜文字、特殊符号、网络用语等 | 默认开启 |
| 双语TTS | 文字显示中文，语音朗读其他语言 | 翻译API + `bilingual_tts` |
| 语音Tool | 模型主动判断何时发送语音 | `enable_speak_tool` |
| 停顿标记 | MiniMax TTS 标点停顿 | `tts_pause_markers` |

所有功能通过配置开关独立控制，关闭即恢复原版行为。

## 🆕 双语TTS

**核心效果**：文字显示中文，语音朗读其他语言（英语/日语/韩语等，可配置）。

### 工作原理

通过独立翻译API实现，与主模型完全解耦：

```
主模型输出：今天心情很好呢~          ← 只输出中文，不需要额外指令
用户看到：  今天心情很好呢~          ← 纯中文文字
TTS调用时： 调翻译API → 英文        ← 仅在生成语音时才翻译
语音朗读：  I'm in a great mood~    ← 翻译后的语音
```

**优势**：
- 主模型不需要管翻译，不会出现标签暴露问题
- 翻译仅在TTS时触发，不浪费token
- 完美兼容AstrBot的分段发送功能（每段独立翻译）
- 翻译用便宜小模型（如gpt-4o-mini），成本极低

### 配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `bilingual_tts` | 双语TTS总开关 | `false` |
| `tts_language` | TTS朗读语言 | `English` |
| `translate_api_base` | 翻译API地址（OpenAI兼容） | 空 |
| `translate_api_key` | 翻译API密钥 | 空 |
| `translate_model` | 翻译模型 | `gpt-4o-mini` |

`tts_language` 可以填任何语言名，例如：`English`、`Japanese`、`Korean`、`French`、`Spanish`、`German` 等。

**翻译API地址示例**：
- OpenAI官方：`https://api.openai.com/v1`
- OpenRouter：`https://openrouter.ai/api/v1`
- 其他兼容OpenAI格式的服务均可

## 🎤 语音Tool

让模型自己判断什么时候该发语音。用户说"说一句话"、"念给我听"、"用语音回答"等，模型会自动调用`speak`工具发送语音消息。

### 配置

在面板中开启 `enable_speak_tool` 即可。

语音Tool走的是包装好的TTS Provider，双语翻译、文字过滤、停顿标记全部自动生效。

默认情况下，`speak` 工具只发送语音，不额外发送文字。用户明确需要文字或翻译对照时，模型可以通过 `caption` 参数附带一条可见翻译文本；`caption` 禁止填写原文。

## ⏸️ MiniMax停顿标记

为MiniMax TTS添加 `<#x#>` 停顿标记，让语音在标点处自然停顿：

- `。？！` → 停顿2拍
- `，、；` → 停顿1拍
- `…—` → 停顿2拍
- 换行 → 停顿2拍

在面板中开启 `tts_pause_markers` 即可。仅对MiniMax TTS有效，其他TTS引擎会忽略这些标记。

## 🚀 安装

### 方法一：GitHub链接安装（推荐）

在AstrBot面板的插件管理中，使用仓库链接安装：

```
https://github.com/chenluQwQ/astrbot_plugin_tts_sanitizer_bilingual
```

安装后重启AstrBot。

### 方法二：ZIP上传安装

下载仓库ZIP，在AstrBot面板中上传安装，安装后重启AstrBot。

### 注意事项

- 如果已安装原版 `tts_sanitizer`，建议先卸载再安装本插件，避免TTS Provider被重复包装
- 首次安装后需要重启AstrBot
- 需要 `aiohttp` 依赖（双语翻译功能），插件会自动安装

## 🎮 命令

| 命令 | 说明 |
|------|------|
| `/tts_bi_test [文本]` | 测试文字过滤效果 |
| `/tts_bi_stats` | 查看插件状态和配置 |
| `/tts_bi_reload` | 重新加载配置 |

## 📝 快速上手

### 只用文字过滤（与原版功能一致）

安装即可，默认开启。

### 双语TTS

1. 开启 `bilingual_tts`
2. 设置 `tts_language`（如 `English`）
3. 填写 `translate_api_base`、`translate_api_key`、`translate_model`
4. 重启AstrBot

### 语音Tool

1. 开启 `enable_speak_tool`
2. 重启AstrBot
3. 对bot说"说一句话"试试

## 原版功能

原版的所有功能均保留，包括：颜文字过滤、特殊符号清理、智能替换、重复字符压缩、超长文本保护、Live Mode 支持、干净卸载等。

详见原项目 [README](https://github.com/Luna-channel/astrbot_plugin_tts_sanitizer)。

## 致谢

感谢 [柯尔](https://github.com/Luna-channel) 开发的原版 TTS 文本过滤插件，本项目基于其 v1.0.1 版本修改。

## 📝 许可证

AGPL-3.0 License - 与原项目保持一致。
