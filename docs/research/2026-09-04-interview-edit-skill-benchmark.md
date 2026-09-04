# Interview Edit Skill 公开案例对标研究

> 核心结论：当前 Skill 的安全边界是对的；深度升级应提高路由、编辑判断和可验证性，而不是在
`SKILL.md` 中堆叠更多 FFmpeg 命令或宣称不存在的能力。

| 项目 | 信息 |
|---|---|
| 调研日期 | 2026-09-04 |
| 调研类型 | Skill 竞品与技术模式对标 |
| 调研深度 | 三层检索，GitHub 实现、Agent Skills 规范与 X 实践讨论交叉对照 |
| 内部数据 | 已纳入项目 Skill、CLI 合同、ADR、M0–M5 验收和实测命令面 |

## Executive Summary

现有 `interview-edit` Skill 只有 39 行，已具备源素材只读、隐私模式、preview-first、QC 和冻结
审批边界，基础正确。缺口主要在五处：自然语言请求的状态路由、不同创作者视频的叙事
决策准则、审批粒度、失败恢复和行为评测。

公开一手证据支持三个设计原则：

1. `SKILL.md` 应是短路由器，细节按需放入 references；
2. LLM 只处理意图、叙事和审阅判断，机械执行由程序和退出码约束；
3. Skill 要像软件一样通过场景集、负例、跨目录调用和可重复验收来演进。

因此 M6 不新增 Skill 内部媒体脚本，而是将它升级为“状态感知的编辑协调层”，并用实际
CLI 和合成项目验证。

## 现状基线

### 内部现状

- `SKILL.md` 触发边界清晰，但缺少“用户语句 → 项目状态 → 命令顺序 → 停止点”路由表。
- `cli-reference.md` 完整，但命令参考与编辑判断混在一个文件中。
- 隐私和 QC 规则已经是不可绕过的强项。
- CLI 已覆盖索引、代理、转录、同步、cut-list、渲染、QC 和版本冻结，所以 Skill 没有理由
  再实现一套脚本执行层。
- 尚无正式自然语言 eval 集和跨目录 Beta 验收。

### 对标基准

| 来源 | 可吸收模式 | 需要避免 |
|---|---|---|
| Agent Skills 规范 | 三层渐进披露；精准 description；聚焦 reference | 把所有说明塞入主文件 |
| Anthropic `skill-creator` | 真实任务 eval、负例、迭代对比 | 只验证 frontmatter 就宣称行为可靠 |
| VexJoy video editing | 判断由 AI，机械执行由脚本；每阶段有 gate | 绕开本项目 CLI 直接生成 FFmpeg 命令 |
| video-automation-skill | 请求路由表、preview 和审批点、重试止损 | 将所有剪辑都强制成一条固定流程 |
| maxazure video-editing | edit brief、style profile、review packet、source receipt 概念 | 2,000+ 行入口、能力列表膨胀、平台规则老化 |
| GitHub 真实问题反馈 | 路由器在建议跳过步骤前必须打开当前真实来源 | 凭记忆或摘要推断当前能力 |

## 假设验证

| 假设 | 结果 | 证据与判断 |
|---|---|---|
| 优秀 Skill 更强调渐进披露 | 已验证 | Agent Skills 规范和 Anthropic 实现都将主文件与按需资源分层。 |
| 确定性操作应交给 CLI | 已验证 | VexJoy 明确区分 AI 判断和程序执行；本项目 M0–M5 实测证明 CLI 已能承担执行真值。 |
| 视频 Skill 需要证据闭环而非一次自动渲染 | 已验证 | 多个视频 Skill 都包含 preflight、preview、review 和 gate；自动叙事质量仍被视为人工判断。 |
| 公开案例可整体复制 | 已证伪 | 大型视频 Skill 包含本项目不具备的下载、生成、发布和平台规则，且主文件过长。 |

## 设计决策

### 1. 保留短入口，增加三类按需参考

- `workflow-router.md`：从用户意图和项目状态选择命令链。
- `editorial-guidance.md`：访谈、口播、教程、评测和 vlog 的叙事准则。
- `review-and-recovery.md`：审批粒度、失败分类、重试止损和交接摘要。

### 2. 为每次编辑建立最小 brief

只在会实质改变剪辑结果时询问：内容类型、受众/发布场景、目标时长、必留信息和禁删范围。
已有 cut-list 或用户给出明确区间时不重复追问。brief 是叙事判断依据，不是新的执行引擎。

### 3. 使审批绑定到确切对象

预览审批、master 审批和 freeze 审批是三个不同决定。后两者必须引用确切 cut-list 或 run ID；早先的宽泛
“可以继续”不作为未来冻结的永久授权。

### 4. 用 eval 验证路由，不用文字长度代替质量

建立至少五组正向场景和三组 near-miss，记录期望命令、禁止命令、审批点和应返回的证据。
结构、引用和命令表可自动校验；模型路由质量需要真实运行或独立评估，不将静态测试冒充为行为验收。

## 反面观点与回应

- **反面观点：把所有视频能力列在一个 Skill 中更容易发现。**
  回应：超长入口会增加与当前任务无关的上下文，也容易宣称 CLI 尚未实现的能力。对本项目而言，
  精准触发词加按需 references 更可靠。
- **反面观点：自然语言 Skill 应该直接自动完成母版和发布。**
  回应：叙事质量和发布权限不是技术可用性问题。预览、release QC 和独立 freeze 审批必须保留。
- **反面观点：X 上的热门技巧足以作为最佳实践。**
  回应：X 只作为趋势和失败模式线索；所有实施决策都回到开放规范、源仓库和本地实测。

## 建议与实施顺序

1. 重写 description 与主路由，保持主文件紧凑。
2. 新增三份聚焦 reference，不复制 CLI 内已存在的参数校验。
3. 新增自然语言 eval 集和结构化合同测试。
4. 用最终 wheel 在源码目录外执行合成项目链，记录跨目录证据。
5. 将新能力定版为 0.6.0，完成 M6 Beta 验收。

## 参考资料

### 一手来源 [T1]

1. [Agent Skills Specification](https://agentskills.io/specification) — frontmatter、渐进披露和资源结构。
2. [Anthropic skills / skill-creator](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md)
   — 场景 eval、迭代和 description 触发评测。
3. [VexJoy video-editing Skill](https://github.com/notque/vexjoy-agent/blob/main/skills/content/video-editing/SKILL.md)
   — AI 判断/确定性执行分层与阶段 gate。
4. [video-automation-skill](https://github.com/officialwhitebird/video-automation-skill/blob/main/SKILL.md)
   — 工作流路由、预览与审批止损。
5. [maxazure/video-editing-skill](https://github.com/maxazure/video-editing-skill/blob/main/SKILL.md)
   — brief、profile、review packet 和证据 gate 概念；同时是入口过长的反例。
6. [mattpocock/skills issue #614](https://github.com/mattpocock/skills/issues/614)
   — 路由器未读当前 Skill 就建议跳步骤的真实失败报告。

### 实践讨论 [T3，仅用于方向性交叉验证]

7. [宝玉：Skill、SubAgent 与上下文管理](https://x.com/dotey/status/2003712630582612066)
   — 主张将繁重中间过程留在文件系统或独立上下文中。
8. [Tessl：将 Skill 作为可评测、可版本化资产](https://x.com/tessl_io/status/2016938081555804272)
   — 强调持续评估与更新，而不是一次性提示词。
9. [Simon Smith：Skill 库重复和老化问题](https://x.com/_simonsmith/status/2029713209179988445)
   — 说明触发范围、去重和维护责任需要明确。

## 未覆盖问题

- 没有可在当前任务内调用的真实跨模型 Skill A/B 评测服务；M6 会明确区分静态合同、本会话自测和独立行为评测。
- 未将公开案例中的平台发布、生成式素材或商业 API 能力纳入 V1；这些需要独立产品决策和授权。
