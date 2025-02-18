import logging
import random
import re

from aiocqhttp import CQHttp

from astrbot.api.all import *
from astrbot.api.event.filter import *

logger = logging.getLogger("astrbot")

@register("astrbot_plugin_anti_porn", "buding", "一个用于反瑟瑟的插件", "1.0.1", "https://github.com/zouyonghe/astrbot_plugin_anti_porn")
class AntiPorn(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config

    async def _admin_check(self, event: AstrMessageEvent, client: CQHttp) -> bool:
        """检查当前 bot 是否是群管理员或群主并且消息发送者不是管理员或群主"""
        try:
            sender_id = int(event.get_sender_id())
            group_id = int(event.get_group_id())
            bot_id = int(event.get_self_id())

            bot_info = await client.get_group_member_info(group_id=group_id, user_id=bot_id, no_cache=True, self_id=int(event.get_self_id()))
            sender_info = await client.get_group_member_info(group_id=group_id, user_id=sender_id, no_cache=True, self_id=int(event.get_self_id()))
            return bot_info.get("role") in ["admin", "owner"] and sender_info.get("role") not in ["admin", "owner"]
        except Exception as e:
            logging.error(f"获取群成员信息失败: {e}")
            return False

    def _in_group_white_list(self, event: AstrMessageEvent) -> bool:
        group_white_list = self.config.get("group_white_list", "").split(";")
        if str(event.get_group_id()) in group_white_list:
            logger.debug(f"群 {event.get_group_id()} 在白名单内，跳过审查")
            return True
        return False

    async def _delete_and_ban(self, event: AstrMessageEvent, message: str, client: CQHttp):
        """删除消息并禁言用户"""
        try:
            await client.delete_msg(
                message_id=int(event.message_obj.message_id),
                self_id=int(event.get_self_id())
            )
            logger.info(f"Anti porn deleted message: {message}")

            await client.set_group_ban(
                group_id=int(event.get_group_id()),
                user_id=int(event.get_sender_id()),
                duration=self.config.get("group_ban_time", 5) * 60,
                self_id=int(event.get_self_id())
            )
            logger.info(f"Banned user: {event.get_sender_id()} for 5 minutes")

        except Exception as e:
            logger.error(f"Failed to delete and ban: {e}")

        event.stop_event()

    def _local_censor_check(self, message: str) -> bool:
        local_censor_keywords = self.config.get("local_censor_keywords", "").split(";")
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

    async def _llm_censor_check(self, event: AstrMessageEvent, message: str):
        """调用 LLM 进行敏感内容检测，只有在消息字数 < 50 并且满足概率要求时才执行"""
        llm_probability = float(self.config.get("llm_censor_probability", 0.1))
        if len(message) > 50 or random.random() > llm_probability:
            return

        """调用 LLM 进行敏感内容检测"""
        provider = self.context.get_using_provider()
        if not provider:
            logger.warning("No available LLM provider")
            return

        custom_guidelines = self.config.get("custom_guideline", "")
        censor_prompt = (
            f"Analyze the following message and determine whether it contains actual pornography or inappropriate content, "
            f"considering the overall context. Do not judge based on isolated words or phrases. "
            f"Additionally, consider the following user-defined guidelines when making your judgment:"
            f"{custom_guidelines}\n\n"
            f"Answer only 'Yes' or 'No' with no additional explanation.\n\n"
            f"Message: {message}"
        )

        try:
            response = await provider.text_chat(censor_prompt, session_id=str(event.get_sender_id()))
            if response and response.completion_text:
                result = response.completion_text.strip().lower()
                return result.startswith("yes") or result.endswith("yes")

        except Exception as e:
            logger.error(f"LLM censor request failed: {e}")

        return

    @event_message_type(EventMessageType.GROUP_MESSAGE, priority=10)
    async def sensor_porn(self, event: AstrMessageEvent):
        """检测消息是否包含敏感内容"""
        if not self.config.get("enable_anti_porn", False):
            return

        if not self._in_group_white_list(event):
            return

        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
        assert isinstance(event, AiocqhttpMessageEvent)
        client = event.bot
        # 检查bot为管理员，消息发送者不为管理员
        if not await self._admin_check(event, client):
            logging.debug("Bot 不是该群管理员，无需检测群聊是否合规")
            return

        for comp in event.get_messages():
            if isinstance(comp, BaseMessageComponent):
                message_content = comp.toString()
                logger.debug(f"Text message content: {message_content}")
                # 本地检查
                if self._local_censor_check(message_content):
                    logger.debug(f"Local sensor found illegal message: {message_content}")
                    await self._delete_and_ban(event, message_content, client)
                    return

                # 调用LLM检测
                if await self._llm_censor_check(event, message_content):
                    logger.debug(f"LLM censor found illegal message: {message_content}")
                    await self._delete_and_ban(event, message_content, client)
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
            yield event.plain_result("📢 反瑟瑟模式已关闭")
        except Exception as e:
            logger.error(f"关闭反瑟瑟模式失败: {e}")
            yield event.plain_result("❌ 关闭失败，请检查配置")

    @permission_type(PermissionType.ADMIN)
    @anti_porn.command("add")
    async def add_to_white_list(self, event: AstrMessageEvent, group_num: str):
        """添加群组到白名单"""
        try:
            group_white_list = self.config.get("group_white_list", "").split(";")
            if group_num in group_white_list:
                yield event.plain_result(f"✅ 群 {group_num} 已在白名单中")
                return

            group_white_list.append(group_num)
            self.config["group_white_list"] = ";".join(filter(None, group_white_list))
            yield event.plain_result(f"✅ 群 {group_num} 已添加到白名单")
        except Exception as e:
            logger.error(f"添加群组到白名单失败: {e}")
            yield event.plain_result("❌ 添加失败，请检查配置")

    @permission_type(PermissionType.ADMIN)
    @anti_porn.command("del")
    async def del_from_white_list(self, event: AstrMessageEvent, group_num: str):
        """从白名单中删除群组"""
        try:
            group_white_list = self.config.get("group_white_list", "").split(";")
            if group_num not in group_white_list:
                yield event.plain_result(f"⚠️ 群 {group_num} 不在白名单中")
                return

            group_white_list.remove(group_num)
            self.config["group_white_list"] = ";".join(filter(None, group_white_list))
            yield event.plain_result(f"✅ 群 {group_num} 已从白名单中移除")
        except Exception as e:
            logger.error(f"从白名单删除群组失败: {e}")
            yield event.plain_result("❌ 删除失败，请检查配置")

    @permission_type(PermissionType.ADMIN)
    @anti_porn.command("list")
    async def list_white_list(self, event: AstrMessageEvent):
        """查询白名单列表"""
        try:
            group_white_list = self.config.get("group_white_list", "").split(";")
            if not group_white_list or all(not g.strip() for g in group_white_list):
                yield event.plain_result("📜 目前白名单为空")
                return

            white_list_str = "\n".join(group_white_list)
            yield event.plain_result(f"📜 当前白名单群组:\n{white_list_str}")
        except Exception as e:
            logger.error(f"查询白名单失败: {e}")
            yield event.plain_result("❌ 查询失败，请检查配置")
