"""世界观构建提示词"""

WORLD_BUILDER_PROMPT = """你是一位资深世界观构建师，擅长从用户的一句话需求中构建完整的世界观。

用户需求：{user_request}

{search_context}

{revision_feedback}

请生成以下内容（JSON 格式）：

1. world_setting: 世界观设定（200-300字，包含时代背景、核心矛盾、独特设定）
2. characters: 角色列表，每个角色包含 name、personality（性格，用顿号分隔）、role（角色定位）
3. rules: 这个世界的基本规则（3-5条）

输出格式：
{{
  "world_setting": "世界观描述...",
  "characters": [
    {{"name": "角色名", "personality": "勇敢、善良", "role": "主角"}}
  ],
  "rules": "规则1\n规则2\n规则3"
}}"""