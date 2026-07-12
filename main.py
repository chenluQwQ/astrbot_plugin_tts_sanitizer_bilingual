from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig
import astrbot.api.message_components as Comp
import asyncio
import re
from typing import Optional, Dict, Any

# 双语 TTS 标签正则：匹配 «TTS»...«/TTS»（支持换行，兼容旧版 Prompt 注入残留）
EN_TAG_PATTERN = re.compile(r'\s*«TTS»\s*(.*?)\s*«/TTS»', re.DOTALL)
CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

# 内置默认值
DEFAULT_REMOVE_PATTERNS = [
    r"[（(][^（()]*[）)]",
    r"[＞>][＿_][＜<]",
    r"[＾^][＿_][＾^]",
    r"[oO][＿_][oO]",
    r"[xX][＿_][xX]",
    r"[－-][＿_][－-]",
    r"[★☆♪♫♬♩♡♥❤️💖💕💗💓💝💟💜💛💚💙🧡🤍🖤🤎💔❣️💋]",
    r"[→←↑↓↖↗↘↙↔↕↺↻]",
]

DEFAULT_FILTER_WORDS = [
    "ω", "Ω", "σ", "Σ", "ε", "д", "Д",
    "´", "`", "＝", "∀", "∇",
    "orz", "OTZ", "QAQ", "QWQ", "TAT", "TUT", "www",
]

DEFAULT_REPLACEMENTS = ["233|哈哈哈", "666|厉害", "999|很棒", "555|呜呜呜"]

# 语言名称快捷映射（支持中文/缩写 → 标准名）
LANG_ALIASES = {
    "英语": "English", "英文": "English", "en": "English", "eng": "English",
    "日语": "Japanese", "日文": "Japanese", "ja": "Japanese", "jp": "Japanese",
    "韩语": "Korean", "韩文": "Korean", "ko": "Korean", "kr": "Korean",
    "法语": "French", "法文": "French", "fr": "French",
    "西班牙语": "Spanish", "西语": "Spanish", "es": "Spanish",
    "德语": "German", "德文": "German", "de": "German",
    "俄语": "Russian", "俄文": "Russian", "ru": "Russian",
    "中文": "Chinese", "中": "Chinese", "zh": "Chinese",
}


@register(
    "tts_sanitizer_bilingual", "柠弥", "TTS文本过滤插件 - 支持双语TTS和语音Tool，基于柯尔的tts_sanitizer扩展", "1.6.0"
)
class TTSSanitizerPlugin(Star):
    def __init__(self, context: Context, config: Optional[AstrBotConfig] = None):
        super().__init__(context)

        if isinstance(config, AstrBotConfig):
            self.config = config
        else:
            self.config = self._get_default_config()

        self._compile_patterns()
        self._wrapped_providers: list = []
        # 运行时覆盖（/tts_bi_lang 命令用），优先级高于面板配置
        self._override_language: str = ""       # 非空时覆盖 tts_language
        self._override_bilingual: Optional[bool] = None  # 非 None 时覆盖 bilingual_tts

    def _get_default_config(self) -> Dict[str, Any]:
        return {
            "enabled": True,
            "max_length": 200,
            "max_processing_length": 10000,
            "remove_patterns": DEFAULT_REMOVE_PATTERNS,
            "filter_words": DEFAULT_FILTER_WORDS,
            "replacement_words": DEFAULT_REPLACEMENTS,
            "max_repeat_count": 2,
            "debug_mode": False,
        }

    def _get_translate_provider_id(self) -> str:
        """获取面板中选定的 AstrBot 翻译模型提供商 ID。"""
        return str(self.config.get("translate_provider_id", "") or "").strip()

    def _has_translate_provider(self) -> bool:
        return bool(self._get_translate_provider_id())

    def _get_tts_language(self) -> str:
        """获取当前 TTS 语言（运行时覆盖 > 面板配置）"""
        return self._override_language or self.config.get("tts_language", "English")

    def _is_bilingual_enabled(self) -> bool:
        """获取当前双语开关状态（运行时覆盖 > 面板配置）"""
        if self._override_bilingual is not None:
            return self._override_bilingual
        return self.config.get("bilingual_tts", False)

    def _resolve_language(self, lang_input: str) -> str:
        """解析语言名称，支持中文/缩写别名"""
        stripped = lang_input.strip()
        return LANG_ALIASES.get(stripped.lower(), stripped)

    def _contains_cjk(self, text: str) -> bool:
        return bool(text and CJK_PATTERN.search(text))

    def _is_chinese_language(self, language: str) -> bool:
        normalized = (language or "").strip().lower()
        return normalized in {"chinese", "zh", "zh-cn", "zh-tw", "mandarin", "中文", "中"}

    def _should_translate_tool_text(self, text: str, target_language: str) -> bool:
        if not text or not target_language:
            return False
        has_cjk = self._contains_cjk(text)
        if self._is_chinese_language(target_language):
            return not has_cjk
        return has_cjk

    async def initialize(self):
        bilingual = self._is_bilingual_enabled()
        has_provider = self._has_translate_provider()
        speak_tool = self.config.get('enable_speak_tool', False)
        logger.info(
            f"TTS文本过滤插件 v1.6.0 已启动 - 双语: {bilingual}, 翻译Provider: {has_provider}, 语音Tool: {speak_tool}"
        )
        try:
            providers = self.context.get_all_tts_providers()
            if providers:
                self._wrap_all_providers()
        except Exception:
            pass

    # =========================================================================
    # 语音 Tool：让模型主动发语音
    # =========================================================================

    @filter.llm_tool(name="speak")
    async def speak_tool(
        self,
        event: AstrMessageEvent,
        text: str,
        language: str = "",
        caption: str = "",
    ) -> MessageEventResult:
        '''发送语音消息。用户要求"说一句话"、"语音回答"、"念出来"时调用。默认只发送语音，不发送文字；需要附带可见翻译时再填写 caption。text必须填写原文，不要自行翻译；插件会按配置自动处理朗读语言。

        Args:
            text(string): 用来生成语音的原文，禁止翻译成其他语言，默认不会作为文字发送
            language(string): 语音目标语言如English/Japanese/Korean，留空用默认
            caption(string): 可选的可见翻译文本。只有用户明确需要文字或翻译对照时才填写；禁止填写原文，留空则只发语音
        '''
        visible_text = caption.strip()
        failure_text = "🎤 语音生成失败，暂时无法发送语音"

        if not self.config.get("enable_speak_tool", False):
            logger.info("🎤 speak tool: 未启用，回退纯文字")
            yield event.plain_result(visible_text or failure_text)
            return

        debug_mode = self.config.get('debug_mode', False)

        try:
            providers = self.context.get_all_tts_providers()
            if not providers:
                logger.warning("🎤 speak tool: 没有可用的 TTS Provider")
                yield event.plain_result(visible_text or failure_text)
                return

            provider = providers[0]

            # --- 准备 TTS 文本 ---
            # 获取原始（未包装）的 get_audio，避免双重翻译
            original_get_audio = getattr(provider, '_tts_bilingual_original_get_audio', None)
            use_original = original_get_audio is not None

            # 决定朗读语言：tool 参数 > 配置默认
            target_language = self._resolve_language(language) if language.strip() else ""
            bilingual_on = self._is_bilingual_enabled() and self._has_translate_provider()
            need_translate = bool(target_language) or bilingual_on

            tts_text = text  # 默认用原文
            final_lang = target_language if target_language else self._get_tts_language()
            pretranslated_by_llm = False

            if need_translate and self._has_translate_provider():
                # 确定最终目标语言
                if self._should_translate_tool_text(text, final_lang):
                    try:
                        translated = await self._translate_text(text, language=final_lang)
                        if translated:
                            tts_text = translated
                            if debug_mode:
                                logger.info(f"🎤🌐 speak tool 翻译: '{text[:30]}...' → [{final_lang}] '{translated[:30]}...'")
                    except Exception as e:
                        logger.warning(f"🎤🌐 speak tool 翻译失败，降级原文: {e}")
                else:
                    # 有些模型会把 tool 参数提前翻译成目标语言；这里避免再交给翻译 API 处理。
                    pretranslated_by_llm = bool(final_lang and not self._is_chinese_language(final_lang) and not self._contains_cjk(text))
                    if pretranslated_by_llm:
                        if debug_mode:
                            logger.info(f"🎤 speak tool: 检测到疑似已翻译参数，跳过翻译 API: [{final_lang}] '{text[:50]}...'")

            # 过滤
            tts_text = self._apply_filters(tts_text)
            if not tts_text.strip():
                yield event.plain_result(visible_text or failure_text)
                return

            if debug_mode:
                logger.info(f"🎤 speak tool: 调用 TTS，文本: '{tts_text[:50]}...'")

            # 用原始 provider 避免双重翻译，如果拿不到就用包装后的
            if use_original:
                audio_path = await original_get_audio(tts_text)
            else:
                audio_path = await provider.get_audio(tts_text)

            if debug_mode:
                logger.info(f"🎤 speak tool: TTS 返回 audio_path={audio_path}")

            if audio_path:
                if visible_text:
                    yield event.plain_result(visible_text)
                yield event.chain_result([Comp.Record(file=audio_path, url=audio_path)])
            else:
                logger.warning("🎤 speak tool: TTS 返回空路径，仅发送文字")
                yield event.plain_result(visible_text or failure_text)

        except Exception as e:
            logger.warning(f"🎤 speak tool 失败: {e}", exc_info=True)
            yield event.plain_result(visible_text or failure_text)

    # =========================================================================
    # 核心：TTS Provider 包装
    # =========================================================================

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self):
        logger.info("TTS过滤: on_astrbot_loaded 钩子被触发")
        self._wrap_all_providers()
        self._register_provider_change_hook()

    def _register_provider_change_hook(self):
        try:
            from astrbot.core.provider.entities import ProviderType
            pm = self.context.provider_manager
            def _on_provider_change(provider_id: str, provider_type, umo):
                if provider_type == ProviderType.TEXT_TO_SPEECH:
                    logger.info(f"TTS过滤: 检测到 TTS Provider 变更({provider_id})，重新包装...")
                    self._wrap_all_providers()
            pm.register_provider_change_hook(_on_provider_change)
            logger.info("TTS过滤: 已注册 Provider 变更钩子")
        except Exception as e:
            logger.warning(f"TTS过滤: 注册 Provider 变更钩子失败: {e}")

    def _wrap_all_providers(self):
        self._unwrap_all_providers()
        logger.info("TTS过滤: 开始包装 TTS Provider...")
        try:
            providers = self.context.get_all_tts_providers()
            logger.info(f"TTS过滤: 获取到 {len(providers) if providers else 0} 个 TTS Provider")
        except Exception as e:
            logger.warning(f"TTS过滤: 获取 TTS Provider 失败: {e}")
            return

        if not providers:
            logger.warning("TTS过滤: 未发现 TTS Provider，包装将不会生效！")
            return

        wrapped_count = 0
        for provider in providers:
            try:
                if self._wrap_provider(provider):
                    wrapped_count += 1
            except Exception as e:
                logger.warning(f"TTS过滤: 包装 Provider 失败: {e}")
                continue

        if wrapped_count > 0:
            logger.info(f"TTS过滤: 已包装 {wrapped_count} 个 TTS Provider")
        else:
            logger.warning("TTS过滤: 未能包装任何 Provider")

    def _wrap_provider(self, provider) -> bool:
        if getattr(provider, '_tts_bilingual_wrapped', False):
            return False

        original_get_audio = provider.get_audio
        plugin = self

        async def wrapped_get_audio(text: str) -> str:
            debug_mode = plugin.config.get('debug_mode', False)
            if debug_mode:
                logger.debug(f"TTS过滤: 原文: {text[:50]}...")

            if not plugin.config.get('enabled', True) or not text:
                return await original_get_audio(text)

            # 清理可能残留的 «TTS» 标签
            text = EN_TAG_PATTERN.sub("", text).strip()
            if not text:
                return await original_get_audio("")

            # === 双语模式：调翻译 API ===
            if plugin._is_bilingual_enabled() and plugin._has_translate_provider():
                try:
                    translated = await plugin._translate_text(text)
                    if translated:
                        if debug_mode:
                            logger.info(f"🌐 双语TTS: '{text[:30]}...' → '{translated[:30]}...'")
                        text = translated  # 替换为翻译后文本，继续走统一流程
                except Exception as e:
                    logger.warning(f"🌐 双语TTS: 翻译失败，降级为中文朗读: {e}")
                    # 降级：继续用原文走下面的普通模式

            # === 统一处理：过滤 + 长度检查 ===
            filtered = plugin._apply_filters(text)
            if not filtered.strip():
                return await original_get_audio("")

            max_len = plugin.config.get('max_length', 200)
            if max_len > 0 and len(filtered) > max_len:
                if debug_mode:
                    logger.info(f"🚫 TTS过滤: 文本 {len(filtered)} 字超过限制 {max_len}，跳过")
                return await original_get_audio("")

            if debug_mode and filtered != text:
                logger.info(f"🔧 TTS过滤: '{text[:30]}...' → '{filtered[:30]}...'")

            return await original_get_audio(filtered)

        provider.get_audio = wrapped_get_audio
        provider._tts_bilingual_wrapped = True
        provider._tts_bilingual_original_get_audio = original_get_audio

        if hasattr(provider, 'support_stream') and provider.support_stream():
            self._wrap_provider_stream(provider)

        self._wrapped_providers.append(provider)
        return True

    def _wrap_provider_stream(self, provider):
        original_get_audio_stream = provider.get_audio_stream
        plugin = self

        async def wrapped_get_audio_stream(
            text_queue: "asyncio.Queue[str | None]",
            audio_queue: "asyncio.Queue[bytes | tuple[str, bytes] | None]",
        ) -> None:
            filtered_queue: asyncio.Queue[str | None] = asyncio.Queue()
            debug_mode = plugin.config.get('debug_mode', False)
            bilingual = plugin._is_bilingual_enabled() and plugin._has_translate_provider()

            async def filter_worker():
                max_len = plugin.config.get('max_length', 200)
                while True:
                    text = await text_queue.get()
                    if text is None:
                        await filtered_queue.put(None)
                        break

                    if not plugin.config.get('enabled', True):
                        await filtered_queue.put(text)
                        continue

                    # 清理 «TTS» 标签残留
                    text = EN_TAG_PATTERN.sub("", text).strip()
                    if not text:
                        continue

                    # 双语模式：翻译后过滤
                    if bilingual:
                        try:
                            translated = await plugin._translate_text(text)
                            if translated:
                                if debug_mode:
                                    logger.info(f"🌐 双语TTS[stream]: '{text[:30]}...' → '{translated[:30]}...'")
                                text = translated  # 替换为翻译后文本，继续走统一流程
                        except Exception as e:
                            logger.warning(f"🌐 双语TTS[stream]: 翻译失败，降级中文: {e}")

                    # 统一处理：过滤 + 长度检查
                    filtered = plugin._apply_filters(text)
                    if not filtered.strip():
                        continue
                    if max_len > 0 and len(filtered) > max_len:
                        if debug_mode:
                            logger.info(f"🚫 TTS过滤[stream]: 文本 {len(filtered)} 字超过限制 {max_len}，跳过")
                        continue

                    await filtered_queue.put(filtered)

            filter_task = asyncio.create_task(filter_worker())
            try:
                await original_get_audio_stream(filtered_queue, audio_queue)
            finally:
                if not filter_task.done():
                    filter_task.cancel()

        provider.get_audio_stream = wrapped_get_audio_stream
        provider._tts_bilingual_original_get_audio_stream = original_get_audio_stream

    def _unwrap_all_providers(self):
        restored_count = 0
        for provider in self._wrapped_providers:
            if hasattr(provider, '_tts_bilingual_original_get_audio'):
                provider.get_audio = provider._tts_bilingual_original_get_audio
                del provider._tts_bilingual_original_get_audio
            if hasattr(provider, '_tts_bilingual_original_get_audio_stream'):
                provider.get_audio_stream = provider._tts_bilingual_original_get_audio_stream
                del provider._tts_bilingual_original_get_audio_stream
            if hasattr(provider, '_tts_bilingual_wrapped'):
                del provider._tts_bilingual_wrapped
            restored_count += 1
        self._wrapped_providers.clear()
        if restored_count > 0:
            logger.info(f"TTS过滤: 已恢复 {restored_count} 个 TTS Provider")

    # =========================================================================
    # AstrBot 内置模型提供商翻译
    # =========================================================================

    async def _translate_text(self, text: str, language: str = "") -> Optional[str]:
        """通过面板选定的 AstrBot 模型提供商翻译文本。

        Args:
            text: 要翻译的文本
            language: 目标语言，留空则使用配置中的 tts_language
        """
        provider_id = self._get_translate_provider_id()
        target_lang = language if language else self._get_tts_language()

        if not provider_id:
            return None

        response = await asyncio.wait_for(
            self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=text,
                system_prompt=(
                    f"You are a translator. Translate the user's text to {target_lang}. "
                    "Keep the same tone and emotion. Output ONLY the translation, "
                    "without explanations, labels, quotes, or emoticons."
                ),
            ),
            timeout=15,
        )
        content = getattr(response, "completion_text", "") if response else ""
        if not content:
            logger.warning(f"🌐 翻译Provider返回空内容: {provider_id}")
            return None
        return content.strip()

    # =========================================================================
    # 过滤逻辑
    # =========================================================================

    def _compile_patterns(self):
        try:
            patterns = self.config.get("remove_patterns", DEFAULT_REMOVE_PATTERNS)
            self.remove_regex = [re.compile(p) for p in patterns]
            count = self.config.get("max_repeat_count", 2)
            self.repeat_regex = re.compile(f"(.)\\1{{{count},}}") if count > 0 else None
            self.replacements = self._parse_replacements()
        except Exception as e:
            logger.warning(f"编译配置失败: {e}")
            self.remove_regex = []
            self.repeat_regex = None
            self.replacements = {}

    def _parse_replacements(self):
        replacements = {}
        for item in self.config.get("replacement_words", DEFAULT_REPLACEMENTS):
            if isinstance(item, str) and "|" in item:
                try:
                    original, replacement = item.split("|", 1)
                    if original.strip() and replacement.strip():
                        replacements[original.strip()] = replacement.strip()
                except ValueError:
                    pass
        return replacements

    def filter_text(self, text: str) -> str:
        if not text:
            return ""
        return self._apply_filters(text)

    def _apply_filters(self, text: str) -> str:
        max_processing_length = self.config.get("max_processing_length", 10000)
        if not text or len(text) > max_processing_length:
            return ""

        # 清理 «TTS» 标签残留
        text = EN_TAG_PATTERN.sub("", text)

        for regex in self.remove_regex:
            text = regex.sub("", text)

        for word in self.config.get("filter_words", DEFAULT_FILTER_WORDS):
            text = text.replace(word, "")

        for original, replacement in self.replacements.items():
            text = text.replace(original, replacement)

        if self.repeat_regex:
            count = self.config.get("max_repeat_count", 2)
            text = self.repeat_regex.sub(lambda m: m.group(1) * count, text)

        text = re.sub(r'["""\u201c\u201d]\s*["""\u201c\u201d]', '', text)
        text = re.sub(r"['''\u2018\u2019]\s*['''\u2018\u2019]", '', text)
        text = re.sub(r'[「」『』【】\[\]]\s*[「」『』【】\[\]]', '', text)

        text = re.sub(r'[,，、;；]\s*(?=[,，、;；\s])', '', text)
        text = re.sub(r'[,，、;；]\s*$', '', text)
        text = re.sub(r'^\s*[,，、;；]\s*', '', text)

        # 停顿标记必须在空白折叠之前处理，否则 \n 会被吃掉
        if self.config.get("tts_pause_markers", False):
            text = text.replace("\n", "<#2#>")
            text = re.sub(r'([。？！?!])', r'\1<#2#>', text)
            text = re.sub(r'([，,、;；])', r'\1<#1#>', text)
            text = re.sub(r'([…—]+)', r'\1<#2#>', text)
            text = re.sub(r'(<#\d#>){2,}', lambda m: m.group(0)[-5:], text)

        text = re.sub(r"\s+", " ", text).strip()

        return text

    def should_skip_tts(self, text: str) -> bool:
        max_len = self.config.get("max_length", 200)
        return not text.strip() or (max_len > 0 and len(text) > max_len)

    # =========================================================================
    # 命令
    # =========================================================================

    @filter.command("tts_bi_lang")
    async def switch_language(self, event: AstrMessageEvent):
        '''快捷切换 TTS 朗读语言。用法：
        /tts_bi_lang          → 查看当前语言
        /tts_bi_lang English  → 切换到英语
        /tts_bi_lang 日语     → 切换到日语（支持中文名和缩写）
        /tts_bi_lang off      → 关闭双语模式
        '''
        full_msg = event.message_str.strip()
        for cmd in ["/tts_bi_lang", "tts_bi_lang"]:
            if full_msg.startswith(cmd):
                user_input = full_msg[len(cmd):].strip()
                break
        else:
            user_input = full_msg

        current_lang = self._get_tts_language()
        bilingual_on = self._is_bilingual_enabled()

        # 无参数：显示当前状态
        if not user_input:
            status = f"✅ {current_lang}" if bilingual_on else "❌ 已关闭"
            has_provider = self._has_translate_provider()
            yield event.plain_result(
                f"🌐 当前 TTS 语言: {status}\n"
                f"翻译Provider: {'✅ 已选择' if has_provider else '❌ 未选择'}\n\n"
                f"用法：/tts_bi_lang <语言> 切换\n"
                f"支持：English, Japanese, Korean, 英语, 日语, 韩语, en, ja, ko ...\n"
                f"/tts_bi_lang off 关闭双语模式"
            )
            return

        # off/关闭：关闭双语模式
        if user_input.lower() in ("off", "关闭", "close", "disable"):
            self._override_bilingual = False
            logger.info("🌐 双语TTS已关闭（通过命令）")
            yield event.plain_result("🌐 双语TTS已关闭，语音将朗读原文")
            return

        # 切换语言
        if not self._has_translate_provider():
            yield event.plain_result("❌ 未选择翻译Provider，无法使用双语TTS\n请先在面板中选择翻译模型提供商")
            return

        new_lang = self._resolve_language(user_input)
        self._override_language = new_lang
        self._override_bilingual = True
        logger.info(f"🌐 TTS语言已切换: {current_lang} → {new_lang}")
        yield event.plain_result(f"🌐 TTS语言已切换: {new_lang}\n语音将朗读 {new_lang}，文字保持中文")

    @filter.command("tts_bi_test")
    async def test_filter(self, event: AstrMessageEvent):
        full_msg = event.message_str.strip()
        for cmd in ["/tts_bi_test", "tts_bi_test"]:
            if full_msg.startswith(cmd):
                user_input = full_msg[len(cmd):].strip()
                break
        else:
            user_input = full_msg

        if not user_input:
            yield event.plain_result("请输入测试文本，例如：\n/tts_bi_test 你好(＾_＾)测试233")
            return

        filtered = self.filter_text(user_input)
        skip = self.should_skip_tts(filtered)

        result = f"""📝 原文 ({len(user_input)} 字符):
{user_input}

🔧 过滤后 ({len(filtered)} 字符):
{filtered or "(空文本)"}

📊 TTS状态: {"❌ 跳过" if skip else "✅ 可朗读"}"""

        yield event.plain_result(result)

    @filter.command("tts_bi_stats")
    async def show_stats(self, event: AstrMessageEvent):
        wrapped_count = len(self._wrapped_providers)
        provider_id = self._get_translate_provider_id()

        result = f"""📊 TTS过滤插件 v1.6.0

• 启用: {"✅" if self.config.get("enabled", True) else "❌"}
• 双语TTS: {"✅ (" + self._get_tts_language() + ")" if self._is_bilingual_enabled() else "❌"}
• 翻译Provider: {"✅ " + provider_id if provider_id else "❌ 未选择"}
• 语音Tool: {"✅" if self.config.get("enable_speak_tool", False) else "❌"}
• 停顿标记: {"✅" if self.config.get("tts_pause_markers", False) else "❌"}
• 已包装 Provider: {wrapped_count} 个"""

        yield event.plain_result(result)

    @filter.command("tts_bi_reload")
    async def reload_config(self, event: AstrMessageEvent):
        try:
            # 清除运行时覆盖，回到面板配置
            self._override_language = ""
            self._override_bilingual = None
            self._compile_patterns()
            self._wrap_all_providers()

            lang = self._get_tts_language()
            bilingual = self._is_bilingual_enabled()
            provider_id = self._get_translate_provider_id()
            speak = self.config.get("enable_speak_tool", False)
            yield event.plain_result(
                f"✅ 配置已重新加载\n"
                f"• 双语TTS: {'✅ (' + lang + ')' if bilingual else '❌'}\n"
                f"• 翻译Provider: {'✅ ' + provider_id if provider_id else '❌'}\n"
                f"• 语音Tool: {'✅' if speak else '❌'}\n"
                f"• 已包装 {len(self._wrapped_providers)} 个 Provider"
            )
        except Exception as e:
            yield event.plain_result(f"❌ 重新加载失败: {e}")

    async def terminate(self):
        self._unwrap_all_providers()
        logger.info("TTS过滤插件已停止，所有 TTS Provider 已恢复原始状态")
