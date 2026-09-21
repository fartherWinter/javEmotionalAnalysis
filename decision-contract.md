# Laya Decision Contract

版本：`1.0`

sidecar 使用 stdin/stdout JSONL。每行一个请求，每个响应携带相同的 `id`。stdout 只允许协议 JSON；日志写入 stderr。

## 请求

`predict` 请求包含 `state.session_id`、`state.recent_messages`、`state.profile_summary`、`state.candidate_memories` 和 `state.user_request`。消息必须已经脱敏，worker 会再次校验疑似密钥。

`check` 请求只检查运行时环境和本地模型状态。

## 决策字段

- `emotion`: `positive | neutral | curious | anxious | frustrated | sad | angry`
- `intent`: `ask_information | request_action | seek_advice | share_experience | emotional_support | casual_chat | correct_assistant | unknown`
- `desired_depth`: 1 至 4
- `needs_clarification`、`use_long_term_memory`、`profile_deviation`: 0 至 1 概率
- `emotion_confidence`、`intent_confidence`、`confidence`: 0 至 1
- `model_version`、`calibration_version`: 可追溯版本字符串
- `fallback`: 是否使用安全回退

fallback 使用 `neutral + unknown + confidence=0`，不能被解释为模型已经完成判断。

## 隐私

成功响应固定包含 `privacy.redacted_input=true` 和 `privacy.raw_messages_persisted=false`。worker 不读取微信数据库、密钥文件或原始聊天持久化数据。
