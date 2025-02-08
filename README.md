# astrbot_plugin_anti_porn

## 介绍
`astrbot_plugin_anti_porn` 是一个 Astrbot 插件，专门用于检测和屏蔽群聊中的不当内容（如涉黄信息）。
该插件支持本地关键字检测和 LLM（大语言模型）智能审查，并在检测到违规内容时自动删除消息并禁言发送者。

## 功能
- **本地关键字检测**：基于配置的敏感词列表检测消息内容。
- **LLM 智能检测**：调用 LLM 进行敏感内容审查（适用于短消息，默认 1% 概率触发）。
- **自动管理**：
  - 删除违规消息
  - 对违规用户进行 5 分钟禁言
  - 仅在机器人具备管理员权限时生效
- **可配置**：
  - `local_censor_keywords`：本地敏感词列表（多个词用 `;` 分隔）
  - `llm_censor_probability`：LLM 审查触发概率（默认 `0.1`）
  - `enable_anti_porn`：是否启用反瑟瑟模式

## 安装与使用
1. **安装插件**
   将插件放入 Astrbot 插件目录（例如 `data/plugins/`）。

2. **配置插件**
   在 `config.yml` 文件中添加以下内容（可根据需求调整）：
   ```yaml
   enable_anti_porn: true
   local_censor_keywords: "敏感词1;敏感词2;敏感词3"
   llm_censor_probability: 0.1
   ```

3. **启用/关闭反瑟瑟模式**（需要管理员权限）
   在群聊中发送命令：
   ```
   /anti_porn
   ```
   机器人将切换模式并反馈当前状态。

## 许可证
MIT License
