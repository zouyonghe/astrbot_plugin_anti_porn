import random
import re

from aiocqhttp import CQHttp

from astrbot.api.all import *
from astrbot.api.event.filter import *


@register(
    "astrbot_plugin_anti_porn",
    "buding",
    "一个用于反瑟瑟的插件",
    "1.0.6",
    "https://github.com/zouyonghe/astrbot_plugin_anti_porn",
)
class AntiPorn(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    def _provider_supports_image(self, provider) -> bool:
        provider_modalities = provider.provider_config.get("modalities") or []
        return not provider_modalities or "image" in provider_modalities

    def _get_censor_provider(
        self,
        config_key: str,
        *,
        require_image_support: bool = False,
    ):
        provider_id = str(self.config.get(config_key, "") or "").strip()
        provider = None

        if provider_id:
            provider = self.context.get_provider_by_id(provider_id)
            if not provider:
                logger.warning(
                    f"Configured censor provider not found: {provider_id}, fallback to current provider"
                )
            elif require_image_support and not self._provider_supports_image(provider):
                logger.warning(
                    f"Configured censor provider does not support image input: {provider_id}, fallback to current provider"
                )
                provider = None

        if not provider:
            provider = self.context.get_using_provider()

        return provider

    async def _admin_check(self, event: AstrMessageEvent, client: CQHttp) -> bool:
        """检查当前 bot 是否是群管理员或群主并且消息发送者不是管理员或群主"""
        try:
            sender_id = int(event.get_sender_id())
            group_id = int(event.get_group_id())
            bot_id = int(event.get_self_id())

            bot_info = await client.get_group_member_info(
                group_id=group_id,
                user_id=bot_id,
                no_cache=True,
                self_id=int(event.get_self_id()),
            )
            sender_info = await client.get_group_member_info(
                group_id=group_id,
                user_id=sender_id,
                no_cache=True,
                self_id=int(event.get_self_id()),
            )
            return bot_info.get("role") in ["admin", "owner"] and sender_info.get(
                "role"
            ) not in ["admin", "owner"]
        except Exception as e:
            logger.error(f"获取群成员信息失败: {e}")
            return False

    def _in_group_sensor_list(self, event: AstrMessageEvent) -> bool:
        group_sensor_list = self.config.get("group_sensor_list", [])
        if str(event.get_group_id()) in group_sensor_list:
            logger.debug(f"群 {event.get_group_id()} 在审查群组名单内")
            return True
        return False

    async def _delete_and_ban(
        self, event: AstrMessageEvent, message: str, client: CQHttp
    ):
        """删除消息并禁言用户"""
        try:
            await client.delete_msg(
                message_id=int(event.message_obj.message_id),
                self_id=int(event.get_self_id()),
            )
            logger.info(f"Anti porn deleted message: {message}")

            await client.set_group_ban(
                group_id=int(event.get_group_id()),
                user_id=int(event.get_sender_id()),
                duration=self.config.get("group_ban_time", 5) * 60,
                self_id=int(event.get_self_id()),
            )
            logger.info(
                f"Banned user: {event.get_sender_id()} for {self.config.get('group_ban_time', 5)} minutes"
            )

        except Exception as e:
            logger.error(f"Failed to delete and ban: {e}")

        event.stop_event()

    def _local_censor_check(self, message: str) -> bool:
        local_censor_keywords = [
            kw.strip()
            for kw in self.config.get("local_censor_keywords", "").split(";")
            if kw.strip()
        ]
        # 如果敏感词列表为空，直接返回 False 或其他适当的处理
        if not local_censor_keywords:
            return False

        message = message.lower()
        # 去除消息中的标点符号和空格
        message = re.sub(r"[^\w\u4e00-\u9fa5]", "", message)  # 保留字母、数字和中文字符

        # 检查是否包含敏感词
        for keyword in local_censor_keywords:
            if keyword.lower() in message:  # 检查敏感词是否在消息中
                return True
        return False

    def _get_custom_guidelines(self) -> str:
        return self.config.get("custom_guidelines", "") or self.config.get(
            "custom_guideline", ""
        )

    async def _llm_censor_check(self, event: AstrMessageEvent, message: str):
        """调用 LLM 进行敏感内容检测，只有在消息字数 < 50 并且满足概率要求时才执行"""
        llm_probability = float(self.config.get("llm_censor_probability", 0.1))
        if len(message) > 50 or random.random() > llm_probability:
            return

        """调用 LLM 进行敏感内容检测"""
        provider = self._get_censor_provider("text_censor_provider_id")
        if not provider:
            logger.warning("No available LLM provider")
            return

        custom_guidelines = self._get_custom_guidelines()
        censor_prompt = (
            "Analyze the following message and determine whether it contains actual pornography, "
            "offensive material, or inappropriate content. Avoid isolated judgment based on specific words or phrases. "
            "It is critical to understand the context of the message when making a decision. "
            "Examine the content holistically, and do not assume intent incorrectly. "
            "Also, consider the following user-defined guidelines when analyzing:\n\n"
            f"{custom_guidelines}\n\n"
            "If the message is determined to contain inappropriate or pornographic content based on the context and guidelines, "
            "answer ONLY 'Yes'. Otherwise, answer ONLY 'No'. Do not include any explanations or additional output.\n\n"
            f"Message: {message}"
        )

        try:
            response = await provider.text_chat(
                censor_prompt, session_id=str(event.get_sender_id())
            )
            if response and response.completion_text:
                result = response.completion_text.strip().lower()
                return result.startswith("yes") or result.endswith("yes")

        except Exception as e:
            logger.error(f"LLM censor request failed: {e}")

        return

    def _collect_image_sources(self, event: AstrMessageEvent) -> list[str]:
        sources: list[str] = []
        seen: set[str] = set()

        def add_source(val: str, origin: str):
            if not val:
                return
            if val in seen:
                return
            seen.add(val)
            sources.append(val)
            logger.debug(f"✓ 收集图片源({origin}): {str(val)[:80]}")

        def extract_from_components(components, origin: str):
            if not components:
                return
            for comp in components:
                try:
                    if comp.__class__.__name__ == "Image":
                        if getattr(comp, "url", None):
                            add_source(comp.url, origin)
                        elif getattr(comp, "file", None):
                            add_source(comp.file, origin)
                        continue

                    if comp.__class__.__name__ == "File":
                        file_val = getattr(comp, "file", None) or getattr(
                            comp, "url", None
                        )
                        add_source(file_val, origin)
                        continue

                    if comp.__class__.__name__ == "Reply" and getattr(
                        comp, "chain", None
                    ):
                        extract_from_components(comp.chain, "引用消息")
                        continue

                    if comp.__class__.__name__ == "Node":
                        node_content = getattr(comp, "content", None)
                        extract_from_components(node_content, "合并转发")
                        continue

                    if comp.__class__.__name__ == "Nodes":
                        nodes = getattr(comp, "nodes", None) or getattr(
                            comp, "list", None
                        )
                        extract_from_components(nodes, "合并转发")
                        continue
                except Exception as e:
                    logger.debug(f"提取图片源异常: {e}")

        try:
            message_chain = event.get_messages()
        except Exception:
            message_chain = getattr(event.message_obj, "message", []) or []

        extract_from_components(message_chain, "当前消息")

        return sources

    async def _llm_image_censor_check(
        self, event: AstrMessageEvent, image_sources: list[str]
    ) -> bool:
        image_probability = float(self.config.get("image_censor_probability", 1.0))
        if image_probability <= 0 or random.random() > image_probability:
            return False

        provider = self._get_censor_provider(
            "image_censor_provider_id",
            require_image_support=True,
        )
        if not provider:
            logger.warning("No available LLM provider")
            return False

        if not self._provider_supports_image(provider):
            logger.debug("Provider does not support image input, skip image censor")
            return False

        custom_guidelines = self._get_custom_guidelines()
        censor_prompt = (
            "Analyze the attached image(s) and determine whether they contain pornography, "
            "explicit nudity, or inappropriate content. Avoid isolated judgment based on specific elements. "
            "It is critical to understand the context of the image when making a decision. "
            "Examine the content holistically, and do not assume intent incorrectly. "
            "Also, consider the following user-defined guidelines when analyzing:\n\n"
            f"{custom_guidelines}\n\n"
            "If any image is determined to contain inappropriate or pornographic content based on the context and guidelines, "
            "answer ONLY 'Yes'. Otherwise, answer ONLY 'No'. Do not include any explanations or additional output."
        )

        for image_source in image_sources:
            try:
                response = await provider.text_chat(
                    censor_prompt,
                    session_id=str(event.get_sender_id()),
                    image_urls=[image_source],
                )
                if response and response.completion_text:
                    result = response.completion_text.strip().lower()
                    if result.startswith("yes") or result.endswith("yes"):
                        return True
            except Exception as e:
                logger.error(
                    f"LLM image censor request failed: {e}, image={str(image_source)[:80]}"
                )

        return False

    @event_message_type(EventMessageType.GROUP_MESSAGE, priority=10)
    async def sensor_porn(self, event: AstrMessageEvent):
        """检测消息是否包含敏感内容"""
        if not self.config.get("enable_anti_porn", False):
            return

        if not self._in_group_sensor_list(event):
            return

        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
            AiocqhttpMessageEvent,
        )

        assert isinstance(event, AiocqhttpMessageEvent)
        client = event.bot
        # 检查bot为管理员，消息发送者不为管理员
        if not await self._admin_check(event, client):
            logger.debug("Bot 不是该群管理员，无需检测群聊是否合规")
            return

        for comp in event.get_messages():
            if isinstance(comp, Plain):
                message_content = comp.toString()
                logger.debug(f"Text message content: {message_content}")
                # 本地检查
                if self._local_censor_check(message_content):
                    logger.debug(
                        f"Local sensor found illegal message: {message_content}"
                    )
                    await self._delete_and_ban(event, message_content, client)
                    return

                # 调用LLM检测
                if await self._llm_censor_check(event, message_content):
                    logger.debug(f"LLM censor found illegal message: {message_content}")
                    await self._delete_and_ban(event, message_content, client)
                    return

        image_sources = self._collect_image_sources(event)
        if image_sources:
            logger.debug(f"Image sources found: {len(image_sources)}")
            if await self._llm_image_censor_check(event, image_sources):
                await self._delete_and_ban(event, "image content", client)
                return

    @command_group("anti_porn")
    def anti_porn(self):
        pass

    @permission_type(PermissionType.ADMIN)
    @anti_porn.command("enable")
    async def enable_anti_porn(self, event: AstrMessageEvent):
        """开启反瑟瑟模式"""
        try:
            if self.config.get("enable_anti_porn", False):
                yield event.plain_result("✅ 反瑟瑟模式已经是开启状态")
                return

            self.config["enable_anti_porn"] = True
            self.config.save_config()
            yield event.plain_result("📢 反瑟瑟模式已开启")
        except Exception as e:
            logger.error(f"开启反瑟瑟模式失败: {e}")
            yield event.plain_result("❌ 开启失败，请检查配置")

    @permission_type(PermissionType.ADMIN)
    @anti_porn.command("disable")
    async def disable_anti_porn(self, event: AstrMessageEvent):
        """关闭反瑟瑟模式"""
        try:
            if not self.config.get("enable_anti_porn", False):
                yield event.plain_result("✅ 反瑟瑟模式已经是关闭状态")
                return

            self.config["enable_anti_porn"] = False
            self.config.save_config()
            yield event.plain_result("📢 反瑟瑟模式已关闭")
        except Exception as e:
            logger.error(f"关闭反瑟瑟模式失败: {e}")
            yield event.plain_result("❌ 关闭失败，请检查配置")

    @permission_type(PermissionType.ADMIN)
    @anti_porn.command("add")
    async def add_to_sensor_list(self, event: AstrMessageEvent, group_id: str):
        """添加群组到审查名单"""
        try:
            group_sensor_list = self.config.get("group_sensor_list", [])
            if not group_id or group_id == "":
                yield event.plain_result("⚠️ 群 {group_id} 不合法")
                return

            if group_id in group_sensor_list:
                yield event.plain_result(f"✅ 群 {group_id} 已在审查名单中")
                return

            group_sensor_list.append(group_id)
            self.config["group_sensor_list"] = group_sensor_list
            self.config.save_config()
            yield event.plain_result(f"✅ 群 {group_id} 已添加到审查名单")
        except Exception as e:
            logger.error(f"添加群组到审查名单失败: {e}")
            yield event.plain_result("❌ 添加失败，请检查配置")

    @permission_type(PermissionType.ADMIN)
    @anti_porn.command("del")
    async def del_from_sensor_list(self, event: AstrMessageEvent, group_id: str):
        """从审查名单中删除群组"""
        try:
            group_sensor_list = self.config.get("group_sensor_list", [])
            if not group_id or group_id == "":
                yield event.plain_result("⚠️ 群 {group_id} 不合法")
                return

            if group_id not in group_sensor_list:
                yield event.plain_result(f"⚠️ 群 {group_id} 不在审查名单中")
                return

            group_sensor_list.remove(group_id)
            self.config["group_sensor_list"] = group_sensor_list
            self.config.save_config()
            yield event.plain_result(f"✅ 群 {group_id} 已从审查名单中移除")
        except Exception as e:
            logger.error(f"从审查名单删除群组失败: {e}")
            yield event.plain_result("❌ 删除失败，请检查配置")

    @permission_type(PermissionType.ADMIN)
    @anti_porn.command("list")
    async def list_sensor_list(self, event: AstrMessageEvent):
        """查询审查群组名单"""
        try:
            group_sensor_list = self.config.get("group_sensor_list", [])
            if not group_sensor_list:
                yield event.plain_result("📜 目前审查群组名单为空")
                return

            sensor_list_str = "\n".join([f"- {item}" for item in group_sensor_list])
            yield event.plain_result(f"📜 当前审查群组名单:\n{sensor_list_str}")
        except Exception as e:
            logger.error(f"查询审查群组名单失败: {e}")
            yield event.plain_result("❌ 查询失败，请检查配置")
