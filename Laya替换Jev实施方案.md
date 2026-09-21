# 使用 Laya 替换 Jev 的微信聊天分析实施方案

## 1. 结论

Laya 可以替换 Jev，承担本系统中的“结构化情绪、意图和回复策略判断”职责，但不能替换整个微信聊天分析系统。

替换后的职责边界如下：

```text
CipherTalk       -> 只读获取微信聊天记录
本地脱敏层        -> 在消息进入模型前处理敏感信息
Laya             -> 输出情绪、意图、回复深度和策略概率
画像与记忆服务    -> 保存长期画像、短期状态和证据
LLM              -> 生成自然语言分析结果或回复建议
```

当前方案中的 Jev 主要是一个决策契约和分析方法，并没有实际集成 Jev 运行时。因此本次替换重点是新增 Laya 推理层，而不是替换 CipherTalk 或修改微信读取链路。

## 2. Laya 适配性

Laya 是 Apache 2.0 授权的本地非自回归决策模型，支持三类问题：

- `choice`：从多个标签中选择一个，并返回概率和置信度。
- `score`：在有序等级中输出分数和分布。
- `noul`：输出某个判断为真的概率。

它可以在一次推理中并行回答多个问题，适合映射现有 Jev 判断字段：

| 当前决策字段 | Laya 类型 | 推荐实现 |
|---|---|---|
| `emotion` | `choice` | positive、neutral、curious、anxious、frustrated、sad、angry |
| `intent` | `choice` | ask_information、request_action、seek_advice、share_experience、emotional_support、casual_chat、correct_assistant |
| `desired_depth` | `score` | 1 至 4 级回复详细程度 |
| `needs_clarification` | `noul` | 是否缺少阻塞性信息 |
| `use_long_term_memory` | `noul` | 是否值得引用长期记忆 |
| `profile_deviation` | `noul` | 是否明显偏离长期交流基线 |

Laya 不能完成以下工作，仍由原系统负责：

- 读取微信 WCDB 数据库；
- 生成完整自然语言回复；
- 自动建立可靠的长期画像；
- 保存、删除和版本化记忆；
- 处理消息脱敏和隐私控制；
- 证明对方的“真实意图”。

## 3. 目标架构

### 3.1 插件目录调整

在现有插件中增加 Python 推理运行时：

```text
jev-wechat-analysis/
├─ .mcp.json
├─ skills/jev-wechat-analysis/
├─ runtime/
│  ├─ ciphertalk-cli/
│  └─ laya_decision/
│     ├─ pyproject.toml
│     ├─ laya_worker.py
│     ├─ questions.py
│     ├─ contract.py
│     └─ requirements.txt
├─ scripts/
│  ├─ launch-ciphertalk-mcp.mjs
│  ├─ launch-laya-worker.ps1
│  ├─ setup-laya.ps1
│  └─ check-laya.ps1
└─ licenses/
   └─ Laya-LICENSE
```

CipherTalk 继续由 Node.js MCP server 负责，Laya 不直接加载微信数据库，也不接触密钥。

### 3.2 进程边界

首版使用 Python sidecar，而不是把 PyTorch 嵌入 Node 进程：

```text
Codex / Skill
      |
      +--> CipherTalk MCP       -> 脱敏消息
      |
      +--> Laya worker (JSONL)  -> 结构化决策
```

原因：

- PyTorch 和 Transformers 依赖体积较大；
- Python 模型崩溃不应影响 CipherTalk MCP；
- 可以独立更新模型和校准参数；
- 没有 Python 或模型时可以回退到中性策略或 LLM 判断。

## 4. Laya 模型选择

默认使用 `laya-multilingual`，由 Router 根据语言和脚本选择模型。微信聊天主要是中文，不能使用英文 checkpoint 作为默认模型。

推荐配置：

```python
from laya import Router

router = Router(
    preload=True,
    device="cuda" if cuda_available else "cpu",
    max_loaded=1,
)
```

实际部署前必须固定模型版本并在本地缓存。首次下载 Hugging Face 模型需要联网，后续推理应支持离线运行。

注意：

- Laya 仓库代码为 Apache 2.0，但发布到 Hugging Face 的模型权重及其依赖仍需逐项核对许可。
- 不把模型权重直接发布到插件市场；个人安装时由用户本地下载。
- 需要验证模型下载地址、哈希和缓存目录，避免在聊天流程中自动下载。
- 多语言模型的公开基准不是微信关系分析基准，不能直接把公开分数当作本项目准确率。

## 5. Sidecar 接口

### 5.1 输入协议

worker 使用一行一个 JSON 的 stdin/stdout 协议。stdout 只能输出协议消息，日志写入 stderr。

```json
{
  "id": "req-001",
  "method": "predict",
  "state": {
    "session_id": "wxid_xxx",
    "recent_messages": [
      {"direction": "in", "timestamp": "2026-09-21T10:00:00+08:00", "content": "已脱敏文本"}
    ],
    "profile_summary": {},
    "candidate_memories": [],
    "user_request": "分析对方当前意图"
  }
}
```

### 5.2 输出协议

```json
{
  "id": "req-001",
  "ok": true,
  "decision": {
    "emotion": "anxious",
    "emotion_confidence": 0.82,
    "intent": "seek_advice",
    "intent_confidence": 0.79,
    "desired_depth": 2.4,
    "needs_clarification": 0.12,
    "use_long_term_memory": 0.68,
    "profile_deviation": 0.21,
    "confidence": 0.78,
    "model": "multilingual"
  },
  "privacy": {
    "redacted_input": true,
    "raw_messages_persisted": false
  }
}
```

模型返回的原始概率保留在本地决策结果中，但给上层策略时必须经过阈值和校准。不要把单一模型概率解释为事实。

## 6. 决策规则

### 6.1 当前消息优先

当前用户明确要求优先于长期画像。例如画像显示用户偏好详细解释，但本轮说“只给结论”，`desired_depth` 应以本轮为准。

### 6.2 低置信度降级

推荐初始策略：

```text
confidence >= 0.80       允许使用对应策略
0.60 <= confidence < 0.80 只作弱提示，不做关系结论
confidence < 0.60        使用 neutral + 中性回复策略
```

阈值必须通过脱敏 fixture 校准，不能直接照搬公开基准。

### 6.3 关系分析限制

Laya 只能判断输入文本中可观察的语言信号。对于“对方到底喜不喜欢我”“是不是故意冷落”等问题，输出必须包含：

1. 最可能解释；
2. 至少一个替代解释；
3. 支持和反对该解释的证据；
4. 可以通过后续沟通验证的建议。

不能把沉默、短回复或回复延迟直接判定为拒绝、操控或恶意。

## 7. 长期画像和短期状态

Laya 只负责生成候选信号，不直接写入长期画像。

### 短期状态

每次分析可以更新：

- 当前情绪；
- 当前意图；
- 当前话题；
- 回复详细程度；
- 未解决问题；
- 最近互动节奏。

### 长期画像

只有以下证据允许进入长期画像：

- 用户明确表达并要求记住的非敏感事实；
- 至少跨两个时间段重复出现的稳定偏好；
- 用户确认过的画像候选。

一次情绪、一次争执或一次“今天简短回答”不得直接成为长期属性。

## 8. 隐私处理

处理顺序必须固定为：

```text
CipherTalk 查询
    -> 本地脱敏
    -> 限制消息数量和时间范围
    -> Laya 判断
    -> 只保存决策摘要和脱敏证据
```

脱敏至少覆盖：

- 手机号；
- 邮箱；
- 身份证号；
- 银行卡号；
- API key、Token、secret、password；
- 用户配置的联系人名称映射。

Laya worker 不读取 `%USERPROFILE%\.miyu\config.json`，不读取微信数据库路径，不读取数据库密钥。它只接收脱敏后的结构化输入。

## 9. 迁移步骤

### 阶段一：接口适配

1. 固化现有 `decision-contract.md`。
2. 编写 `questions.py`，将 Jev 字段转换为 Laya question schema。
3. 实现 JSONL worker 和超时处理。
4. 加入 Python 版本、模型缓存和依赖检查脚本。

### 阶段二：双路验证

1. 同一批脱敏 fixture 同时送入现有 LLM/Jev 方案和 Laya。
2. 比较 emotion、intent、desired_depth 和各概率分布。
3. 记录误判、过度自信和中文口语场景失败样本。
4. 先让 Laya 只提供建议，不影响最终回复策略。

### 阶段三：启用 Laya

1. Laya 置信度达到阈值时采用其决策。
2. 低置信度时回退到中性策略或 LLM 判断。
3. 保留 `model`、`confidence`、`calibration_version` 和证据引用。
4. 不改变 CipherTalk 的查询工具和只读边界。

### 阶段四：领域微调

1. 建立脱敏中文单聊数据集。
2. 为情绪、意图、回复深度和澄清需求分别标注。
3. 按联系人和会话切分训练集、验证集，避免同一聊天泄漏到两边。
4. 重新拟合温度校准，并通过人工评审确认关系推断没有过度解释。

## 10. 测试计划

### 单元测试

- 问题 schema 能覆盖所有决策字段；
- JSONL 请求和响应可连续处理；
- 无效 JSON、未知方法、超时和 worker 退出时返回明确错误；
- 输出字段符合 `decision-contract.md`；
- 输入不包含原始密钥和未脱敏敏感字段。

### 模型测试

- 中文简短口语；
- 中英夹杂；
- 表情、链接、图片和语音占位消息；
- 讽刺、反问、模糊表达；
- 主动关心、寻求建议、冲突、拒绝和边界表达；
- 消息不足、证据冲突和长期画像过时。

### 集成测试

```powershell
python -m runtime.laya_decision.laya_worker --check
python -m pytest runtime/laya_decision/tests
node scripts/launch-ciphertalk-mcp.mjs
```

需要验证：

- CipherTalk 读取失败不导致 Laya 误判；
- Laya 进程退出后可以回退；
- 不发送、不修改、不删除微信数据；
- MCP stdout 不混入调试日志；
- 结果中 `redacted_input=true` 且 `raw_messages_persisted=false`。

## 11. 风险与回退

| 风险 | 控制措施 |
|---|---|
| 基础模型中文关系判断不准 | 使用中文 fixture 校准，后续领域微调 |
| 模型概率过度自信 | 温度校准、置信度阈值、低置信度中性回退 |
| CPU 推理延迟过高 | 预加载、限制消息窗口、可选 GPU、超时回退 |
| Python/PyTorch 安装复杂 | 独立 sidecar、明确检查脚本、不影响 CipherTalk |
| 首次下载模型需要联网 | 安装阶段下载并校验，聊天时禁止隐式下载 |
| 模型或权重许可变化 | 锁定版本，交付前核对代码和模型卡许可证 |
| 错误画像固化 | Laya 只生成候选，画像需证据门槛和用户确认 |

如果 Laya 不可用，系统继续返回：

```json
{
  "decision": {
    "emotion": "neutral",
    "intent": "unknown",
    "confidence": 0.0,
    "fallback": true
  }
}
```

LLM 可以在此基础上继续生成谨慎的分析，但不得声称 Laya 已完成判断。

## 12. 验收标准

完成替换后应满足：

1. Windows 本机可以独立启动 CipherTalk MCP 和 Laya worker。
2. Laya 能在一次调用中返回六类 Jev 决策字段。
3. 中文脱敏聊天 fixture 的准确率、召回率和校准误差达到项目设定门槛。
4. 低置信度样本不会触发强关系结论或自动画像更新。
5. Laya worker 不接触微信密钥和原始数据库。
6. 无 Python、无模型或推理失败时，插件仍能安全回退。
7. 不发送、不修改、不删除微信消息。
8. 许可证、模型版本和缓存来源可追溯。

## 13. 最终建议

采用“CipherTalk + Laya + LLM”的组合，而不是把 Laya 当成完整聊天分析系统：

```text
CipherTalk 负责事实数据
Laya       负责快速类型化判断
画像服务   负责长期记忆和证据
LLM        负责自然语言解释和沟通建议
```

首版先做 sidecar 和双路评估，验证中文微信场景后再让 Laya 成为默认决策引擎。未经领域校准，不建议直接删除现有的中性回退和人工可解释证据链。
