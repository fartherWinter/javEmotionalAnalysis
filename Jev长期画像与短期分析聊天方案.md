# 基于长期画像与短期分析的 Jev 智能聊天方案

## 1. 方案概述

本方案用于普通聊天、陪伴对话、个人助理和客服会话等场景。

系统从长期聊天记录中提炼用户稳定画像，从最近几轮对话中分析当前情绪、意图、话题和回复偏好，再由大语言模型生成自然回复。Jev 不直接负责聊天内容生成，而是作为快速、结构化的判断层。

```text
长期聊天记录 -> 用户画像与偏好 --------+
最近几轮对话 -> 当前情绪、意图、话题 --+--> Jev 类型化判断
当前用户消息 -------------------------+         |
                                                 v
                                         回复策略组装
                                                 |
                                                 v
                                         LLM 生成自然回复
                                                 |
                                                 v
                                      保存会话与更新记忆候选
```

核心思想：

```text
长期画像回答“这个用户通常怎样”
短期分析回答“这个用户现在怎样”
Jev 判断“这一轮应该采用什么回复策略”
LLM 决定“具体怎么说”
```

## 2. 建设目标

1. 让聊天系统记住用户稳定偏好，减少重复询问。
2. 理解当前消息的情绪、意图、话题和期望回复方式。
3. 区分长期特征与临时状态，避免一次对话污染用户画像。
4. 控制发送给生成模型的上下文规模，降低延迟和 Token 成本。
5. 使画像、判断和回复策略可追溯、可修正、可删除。
6. 通过用户反馈持续调整画像、规则和阈值。

## 3. 适用场景

- 日常陪伴聊天。
- 个人知识助理。
- 智能客服和售后对话。
- 学习辅导与职业咨询。
- 社区聊天机器人。
- 游戏 NPC 或虚拟角色对话。

本方案不适合仅依靠模型处理医疗诊断、法律裁决、信贷审批等高风险决策。

## 4. 核心设计原则

### 4.1 Jev 判断，LLM 表达

Jev 适合快速完成有限答案空间内的判断：

- 用户当前是什么情绪。
- 用户是在提问、倾诉、分享还是请求行动。
- 这一轮适合简短回答还是详细解释。
- 是否应该主动引用长期记忆。
- 是否需要追问澄清。

Jev 不适合生成完整回复、总结长对话或编写开放式内容，这些任务交给生成模型。

### 4.2 长期画像保持结构化

不要只保存一段“用户人设总结”。应保存独立字段、证据、置信度和更新时间，便于局部更新和撤销。

### 4.3 短期状态不直接写入长期画像

用户今天心情低落，不代表其长期性格悲观；用户一次要求简短回答，也不代表永远偏好简短内容。

### 4.4 事实与推断分开

```text
事实：用户明确说“我主要写 Java 后端”
推断：用户可能偏好工程化解释
```

事实可以直接保存；推断必须带置信度和证据，并允许过期。

### 4.5 用户当前表达优先

当前消息明确提出的要求优先于历史偏好。例如画像记录“偏好详细解释”，但本轮用户说“只给结论”，系统必须简短回答。

## 5. 总体架构

```text
客户端
  |- Web / App / IM
  v
Chat API
  |- 鉴权、限流、会话管理
  v
上下文编排服务
  |- 读取长期画像
  |- 读取近期会话
  |- 检索相关长期记忆
  v
Jev 判断服务
  |- 当前情绪
  |- 当前意图
  |- 回复风格
  |- 是否引用记忆
  |- 是否需要澄清
  v
回复策略服务
  |- 确定 Prompt 和回复约束
  |- 选择必要上下文
  v
LLM 生成服务
  |- 生成最终自然语言回复
  v
记忆处理服务
  |- 保存消息
  |- 提取记忆候选
  |- 更新短期状态
  |- 异步维护长期画像
```

推荐存储：

- MySQL：用户画像、长期记忆、会话元数据和版本记录。
- Redis：活跃会话、最近消息、短期状态和幂等控制。
- 对象存储：可选，用于归档长会话或附件。
- 向量库：可选，仅在长期记忆规模较大、需要语义检索时引入。

## 6. 记忆分层

### 6.1 长期画像

长期画像保存用户相对稳定的信息：

```json
{
  "user_id": "user-1001",
  "profile_version": 12,
  "language": "zh-CN",
  "preferred_response_style": {
    "value": "concise_engineering",
    "source": "inferred",
    "confidence": 0.84,
    "evidence_count": 16,
    "updated_at": "2026-09-21T10:00:00+08:00",
    "expires_at": "2026-12-20T10:00:00+08:00"
  },
  "technical_background": [
    {
      "value": "java_backend",
      "source": "user_explicit",
      "confidence": 1.0,
      "evidence_refs": ["message-8831"]
    }
  ],
  "recurring_interests": ["Go", "Python", "AI engineering"],
  "conversation_preferences": {
    "likes_examples": true,
    "likes_java_comparisons": true,
    "avoid_excessive_formatting": true
  }
}
```

推荐保存：

- 用户主动声明的背景和偏好。
- 多次稳定出现的兴趣和交流习惯。
- 用户要求系统记住的事实。
- 对后续聊天确有帮助的长期目标。

不建议保存：

- 单次情绪和临时抱怨。
- 未经用户确认的敏感属性。
- 对后续对话没有价值的琐碎信息。
- 密码、Token、证件号码等秘密信息。

### 6.2 长期事件记忆

除画像外，可以保存对未来聊天有用的具体事件：

```json
{
  "memory_id": "memory-3102",
  "user_id": "user-1001",
  "type": "project_context",
  "content": "用户正在设计基于 Jev 的聊天情绪判断方案",
  "importance": 0.78,
  "confidence": 0.96,
  "source_message_ids": ["message-9001", "message-9004"],
  "created_at": "2026-09-21T10:20:00+08:00",
  "expires_at": null
}
```

画像描述稳定特征，事件记忆描述发生过的事情，两者不要混为一个大文本字段。

### 6.3 短期会话状态

短期状态只服务当前会话：

```json
{
  "session_id": "session-20260921-001",
  "recent_messages": [
    {"role": "user", "content": "我最近在研究 Jev"},
    {"role": "assistant", "content": "它适合快速类型化判断"},
    {"role": "user", "content": "我想把它用到普通聊天里"}
  ],
  "current_topic": "Jev 聊天分析",
  "current_emotion": "curious",
  "current_intent": "solution_design",
  "reply_preference": "practical",
  "unresolved_questions": []
}
```

默认保留最近 5 至 12 轮相关消息。超过窗口的内容先提取事实和未解决事项，再从活跃上下文移除。

## 7. Jev 实时判断设计

一次调用可以并行执行以下原子问题：

```json
{
  "emotion": {
    "type": "choice",
    "instructions": "判断用户当前消息的主要情绪。无法明确判断时选择 neutral。",
    "criteria": {
      "positive": "开心、满意、兴奋或赞同",
      "neutral": "主要在陈述、询问或讨论，没有明显情绪",
      "curious": "表现出探索、好奇或求知欲",
      "anxious": "担忧、紧张、犹豫或反复确认",
      "frustrated": "受挫、不耐烦或对结果不满",
      "sad": "低落、失望或悲伤",
      "angry": "明显愤怒、指责或攻击"
    }
  },
  "intent": {
    "type": "choice",
    "instructions": "判断用户当前最主要的交流意图。",
    "criteria": {
      "ask_information": "询问事实、概念或解释",
      "request_action": "要求系统执行具体任务",
      "seek_advice": "寻求建议、方案或比较",
      "share_experience": "分享经历、观点或结果",
      "emotional_support": "倾诉并希望获得理解或支持",
      "casual_chat": "寒暄或开放式闲聊",
      "correct_assistant": "纠正系统之前的理解或输出"
    }
  },
  "desired_depth": {
    "type": "score",
    "instructions": "判断本轮回复适合的详细程度。",
    "criteria": [
      "只需一句简短回应",
      "简洁回答并给出关键依据",
      "提供结构化解释和示例",
      "提供完整方案和实施细节"
    ]
  },
  "needs_clarification": {
    "type": "noul",
    "instructions": "用户请求是否缺少会显著改变答案的关键信息？普通细节缺失不应要求澄清。"
  },
  "use_long_term_memory": {
    "type": "noul",
    "instructions": "引用提供的长期画像或事件记忆是否能明显改善当前回复？不要为了展示记忆而强行引用。"
  },
  "profile_deviation": {
    "type": "noul",
    "instructions": "当前表达是否明显偏离用户长期交流基线？只在差异清晰且与回复策略有关时返回高概率。"
  }
}
```

### 7.1 Jev 输入状态

```json
{
  "current_message": "别讲太多，告诉我这个方案最大的风险",
  "recent_messages": [
    "我想把长期画像和短期情绪结合起来",
    "能否给一个完整架构？"
  ],
  "profile_summary": {
    "preferred_response_style": "concise_engineering",
    "technical_background": ["java_backend"]
  },
  "candidate_memories": [
    "用户正在设计基于 Jev 的普通聊天方案"
  ]
}
```

只向 Jev 发送当前判断所需字段，不发送完整历史聊天。

## 8. 回复策略

Jev 返回类型化判断后，由策略服务生成回复约束：

| 判断结果 | 回复策略 |
|---|---|
| `ask_information` | 直接回答，优先事实准确性 |
| `seek_advice` | 给出建议、取舍和推荐方案 |
| `emotional_support` | 先回应感受，再讨论解决方案 |
| `correct_assistant` | 承认偏差，按最新要求修正，不重复辩解 |
| `desired_depth` 较低 | 限制段落和示例数量 |
| `needs_clarification` 高 | 只询问一个真正阻塞的问题 |
| `use_long_term_memory` 高 | 选择最相关的一至三条记忆加入上下文 |
| Jev 低置信度 | 使用中性默认策略，不强行个性化 |

生成模型收到的 Prompt 不需要包含全部概率，只包含最终选定的策略和必要证据：

```text
用户背景：Java 后端开发者，学习 Go 和 Python。
本轮意图：寻求方案建议。
当前情绪：好奇，未表现出明显负面情绪。
回复要求：简洁、工程化，给出主要风险和推荐做法。
相关记忆：用户正在设计基于 Jev 的普通聊天系统。
禁止事项：不要声称记得未提供的信息，不要强行提及用户画像。
```

## 9. 消息处理流程

```text
1. 接收用户消息并生成 message_id
2. 将原始消息持久化
3. 从 Redis 读取最近会话窗口
4. 从 MySQL 读取长期画像
5. 根据当前消息检索少量相关长期记忆
6. 调用 Jev 并行判断情绪、意图和回复策略
7. 策略服务选择要发送给 LLM 的上下文
8. LLM 流式生成最终回复
9. 保存回复和本轮 Jev 判断
10. 异步提取长期记忆候选
11. 根据证据门槛更新画像或进入待确认状态
```

Jev 超时或不可用时，不应阻断普通聊天：使用默认中性策略继续调用生成模型。

## 10. 长期画像更新机制

### 10.1 更新来源

- 用户明确表达：“以后回答短一点。”
- 多个独立会话中重复出现的稳定偏好。
- 用户对系统回复的接受、修改或否定。
- 用户主动要求记住或忘记的信息。

### 10.2 更新状态

```text
observed  -> candidate -> confirmed -> active -> expired/deleted
观察到       候选       已确认       生效       过期或删除
```

### 10.3 默认规则

- 用户明确声明的非敏感偏好可直接进入 `confirmed`。
- 模型推断至少需要跨两个会话、三条一致证据。
- 新旧证据冲突时降低置信度，不立即覆盖。
- 连续长期未出现的推断型偏好逐渐衰减。
- 用户纠正画像时，以用户明确表达为准。
- 所有画像变化保留版本和证据引用。

示例：

```text
“这次回答简短点” -> 仅影响当前会话
“以后都直接给结论” -> 更新长期回复偏好
连续多次跳过长解释 -> 生成偏好候选，不自动断言
```

## 11. Java 后端模块建议

```text
chat-api
  |- ChatController
  |- ChatApplicationService

conversation-domain
  |- Conversation
  |- Message
  |- ShortTermState

profile-domain
  |- UserProfile
  |- ProfileAttribute
  |- MemoryItem
  |- ProfileUpdatePolicy

decision-integration
  |- JevClient
  |- JevDecisionService
  |- ReplyPolicyAssembler

generation-integration
  |- LlmClient
  |- PromptAssembler

infrastructure
  |- MyBatis Mapper
  |- Redis Repository
  |- Outbox Event Publisher
```

关键接口示例：

```java
public interface ConversationDecisionService {
    ConversationDecision analyze(DecisionContext context);
}

public record ConversationDecision(
        Emotion emotion,
        Intent intent,
        double desiredDepth,
        double needsClarificationProbability,
        double useMemoryProbability,
        double confidence) {
}
```

### 11.1 事务边界

- 用户消息入库与会话版本更新放在一个本地事务中。
- 外部 Jev 和 LLM 调用不要放在数据库事务内。
- 回复结果单独提交，并通过请求 ID 保证幂等。
- 画像更新通过异步事件执行，避免增加聊天首 Token 延迟。

## 12. 数据表建议

### `chat_message`

- `id`
- `session_id`
- `user_id`
- `role`
- `content`
- `created_at`
- `request_id`

### `user_profile_attribute`

- `id`
- `user_id`
- `attribute_key`
- `attribute_value_json`
- `source_type`
- `confidence`
- `evidence_count`
- `status`
- `version`
- `updated_at`
- `expires_at`

### `long_term_memory`

- `id`
- `user_id`
- `memory_type`
- `content`
- `importance`
- `confidence`
- `source_message_ids_json`
- `created_at`
- `expires_at`
- `deleted_at`

### `conversation_decision_log`

- `id`
- `message_id`
- `model_version`
- `question_version`
- `decision_json`
- `latency_ms`
- `created_at`

## 13. 缓存与上下文控制

Redis 建议保存：

- 最近 5 至 12 轮消息。
- 当前话题、临时偏好和未解决问题。
- 会话版本号和请求幂等键。
- 最近一次 Jev 判断结果，可按消息 ID 去重。

不要缓存完整长期画像副本而不设置版本。推荐缓存：

```text
profile:{userId}:{profileVersion}
session:{sessionId}:recentMessages
session:{sessionId}:shortTermState
request:{requestId}:result
```

上下文预算应优先分配给：

1. 当前用户消息。
2. 最近相关消息。
3. 当前未解决的问题。
4. 与当前话题相关的长期记忆。
5. 少量稳定画像字段。

## 14. 隐私与用户控制

1. 提供“你记住了什么”的查询入口。
2. 允许用户修改或删除单条画像和记忆。
3. 用户说“忘掉这件事”时应真正删除或进入可审计删除流程。
4. 不把密码、Token、银行卡号等内容写入长期记忆。
5. 敏感属性默认不推断、不持久化。
6. 发送给外部模型的数据遵循最小必要原则。
7. 日志记录消息 ID 和决策摘要，避免重复记录完整私密聊天。

## 15. 评估指标

### 15.1 Jev 判断质量

- 情绪分类准确率和混淆矩阵。
- 意图分类 Macro-F1。
- Noul 概率的 Brier Score 和校准误差。
- 低置信度样本占比。
- 不同语言和表达风格下的差异。

### 15.2 聊天体验

- 用户继续对话率。
- 用户修改或重问率。
- 回复被接受、点赞或复制的比例。
- 不必要澄清问题比例。
- 画像引用命中率及用户反感率。
- 首 Token 延迟和完整回复延迟。

### 15.3 记忆质量

- 画像候选被用户确认或否定的比例。
- 错误记忆率。
- 过期记忆仍被引用的比例。
- 单用户长期画像大小。
- 用户删除请求完成率。

## 16. 分阶段实施

### 阶段一：基础聊天

- 接入普通 LLM 聊天。
- 保存会话和最近消息。
- Jev 只判断情绪、意图和期望详细度。
- 不生成长期画像。

### 阶段二：显式长期记忆

- 只保存用户明确要求记住的信息。
- 提供记忆查询、修改和删除入口。
- 根据 Jev 判断决定是否引用记忆。

### 阶段三：画像候选

- 异步分析长期记录并生成画像候选。
- 候选达到证据门槛后提示用户确认或自动低权重启用。
- 建立版本、过期和冲突处理机制。

### 阶段四：个性化闭环

- 使用用户反馈调整回复策略。
- 对画像引用和回复效果进行 A/B 测试。
- 建立固定评估集和版本发布门禁。

## 17. 推荐 MVP

首个版本建议只实现以下范围：

```text
输入：当前消息 + 最近 6 轮对话 + 少量显式用户偏好

Jev 判断：
- emotion
- intent
- desired_depth
- needs_clarification
- use_long_term_memory

LLM 输出：
- 根据判断结果生成最终回复

长期记忆：
- 只保存用户明确要求记住的内容
- 暂不自动推断复杂人格
```

该范围足以验证 Jev 是否能改善聊天体验，同时避免一开始就引入复杂画像污染、向量检索和自动记忆更新。

## 18. 主要风险

1. **画像固化**：系统根据旧记录形成刻板印象，忽略用户变化。
2. **错误记忆**：模型把推断当成事实，后续反复引用。
3. **过度个性化**：频繁提及历史信息，让用户感到被监视。
4. **短期状态污染**：一次情绪波动被写成长期特征。
5. **上下文膨胀**：画像和记忆过多，反而降低生成质量。
6. **额外延迟**：Jev 调用增加回复链路耗时。
7. **隐私风险**：私密聊天被发送给外部模型或长期保存。

对应控制措施是结构化存储、证据追踪、版本化、过期机制、最小上下文、异步画像更新以及完整的用户记忆控制。

## 19. 结论

普通聊天场景中，Jev 最合适的定位不是聊天模型，而是生成模型前的实时决策层：

```text
历史记录 -> 稳定画像与相关记忆
近期对话 -> 当前状态
Jev      -> 类型化回复策略
LLM      -> 自然语言表达
反馈     -> 修正画像与策略
```

第一阶段应保持简单：先用 Jev 判断情绪、意图和回复深度，只保存用户明确要求记住的内容。验证体验改善后，再逐步加入自动画像候选、相关记忆检索和反馈闭环。
