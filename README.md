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
  - `group_white_list`：白名单群组（多个群用 `;` 分隔）

## 安装与使用
1. **安装插件**
   将插件放入 Astrbot 插件目录（例如 `data/plugins/`）。

2. **配置插件**
   在插件配置页设置。

3. **命令列表**（需要管理员权限）
   - **启用反瑟瑟模式**
     ```
     /anti_porn enable
     ```
   - **禁用反瑟瑟模式**
     ```
     /anti_porn disable
     ```
   - **添加群组到白名单**
     ```
     /anti_porn add <群号>
     ```
   - **从白名单中删除群组**
     ```
     /anti_porn del <群号>
     ```
   - **查询群白名单列表**
     ```
     /anti_porn list
     ```

## 许可证
MIT License
