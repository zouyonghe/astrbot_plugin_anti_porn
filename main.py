import logging
import random
import re

from astrbot.api.event import filter
from astrbot.api.event.filter import *
from aiocqhttp import CQHttp

from astrbot.api.all import *

logger = logging.getLogger("astrbot")

@register("astrbot_plugin_anti_porn", "buding", "一个用于反瑟瑟的插件", "1.0.0", "https://github.com/zouyonghe/astrbot_plugin_anti_porn")
class AntiPorn(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.bot = CQHttp
        self.config = config

    async def _is_self_admin(self, event: AstrMessageEvent) -> bool:
        """检查当前 bot 是否是群管理员或群主"""
        try:
            self_id = int(event.get_self_id())
            group_id = int(event.get_group_id())
            member_info = await self.bot.get_group_member_info(group_id=group_id, user_id=self_id)
            return member_info.get("role") in ["admin", "owner"]
        except Exception as e:
            logging.error(f"获取群成员信息失败: {e}")
            return False

    async def _delete_and_ban(self, event: AstrMessageEvent, message: str):
        """删除消息并禁言用户"""
        try:
            await self.bot.delete_msg(
                message_id=int(event.message_obj.message_id),
                self_id=int(event.get_self_id())
            )
            logger.info(f"Anti porn deleted message: {message}")

            await self.bot.set_group_ban(
                group_id=int(event.get_group_id()),
                user_id=int(event.get_sender_id()),
                duration=5 * 60,
                self_id=int(event.get_self_id())
            )
            logger.info(f"Banned user: {event.get_sender_id()} for 5 minutes")

        except Exception as e:
            logger.error(f"Failed to delete and ban: {e}")

        await event.stop_event()

    def _local_censor_check(self, message: str) -> bool:
        local_censor_keywords = self.config.get("local_censor_keywords", "").split(";")

        # 将消息转换为小写，避免大小写干扰
        message = message.lower()

        # 去除消息中的标点符号和空格
        # 在中文中，标点符号需要特别处理
        message = re.sub(r"[^\w\u4e00-\u9fa5\s]", "", message)  # 保留中文字符和字母数字

        # 检查是否包含敏感词
        for keyword in local_censor_keywords:
            # 如果敏感词在消息中以完整词的形式出现，则认为包含该敏感词
            # 在中文中，敏感词可能是连续字符，因此这里不需要空格分隔
            if re.search(r"\b" + re.escape(keyword.lower()) + r"\b", message):
                return True
        return False

    async def _llm_censor_check(self, event: AstrMessageEvent, message: str) -> bool:
        """调用 LLM 进行敏感内容检测，只有在消息字数 < 50 并且满足概率要求时才执行"""
        llm_probability = float(self.config.get("llm_censor_probability", 0.1))
        if len(message) > 50 or random.random() > llm_probability:
            return False

        """调用 LLM 进行敏感内容检测"""
        provider = self.context.get_using_provider()
        if not provider:
            logger.warning("No available LLM provider")
            return False

        censor_prompt = (
            f"Does the following message contain pornography or inappropriate content? "
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

        return False

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE, priority=10)
    async def sensor_porn(self, event: AstrMessageEvent):
        """检测消息是否包含敏感内容"""

        # 检查 Bot 是否为管理员
        if not await self._is_self_admin(event):
            logging.info("Bot 不是该群管理员，无需检测群聊是否合规")
            return
        logger.info("SENSOR CALLED")

        for comp in event.get_messages():
            if isinstance(comp, BaseMessageComponent):
                message_content = comp.toString()
                logger.info(f"Text message content: {message_content}")
                # 本地检查
                if self._local_censor_check(message_content):
                    logger.info(f"Local sensor found illegal message: {message_content}")
                    await self._delete_and_ban(event, message_content)
                    return

                # 调用LLM检测
                if await self._llm_censor_check(event, message_content):
                    logger.info(f"LLM censor found illegal message: {message_content}")
                    await self._delete_and_ban(event, message_content)
                    return

    @permission_type(PermissionType.ADMIN)
    @command("anti_porn")
    async def anti_porn(self, event: AstrMessageEvent):
        """切换反瑟瑟模式（enable_anti_porn）"""
        try:
            # 读取当前状态并取反
            current_set = bool(self.config.get("enable_anti_porn", False))
            new_set = not current_set

            # 更新配置
            self.config["enable_anti_porn"] = new_set

            # 发送反馈消息
            status = "开启" if new_set else "关闭"
            yield event.plain_result(f"📢 反瑟瑟模式已{status}")
        except Exception as e:
            logger.error(f"切换反瑟瑟模式失败: {e}")
            yield event.plain_result("❌ 切换反瑟瑟模式失败，请检查配置")
