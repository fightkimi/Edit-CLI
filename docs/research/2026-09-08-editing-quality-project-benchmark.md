# 剪辑质量优化：GitHub / X 项目对标

调研日期：2026-09-08。内部基线：`847bfcfefd393a980788556b2d208cd45c987958`。
范围：访谈、口播、教程、评测、vlog 的剪辑输出；比较公开实现与本项目的实际代码。
本次仅调研和小型复现，不安装新运行时、不修改产品代码、不处理真实素材。

## 结论

建议下一轮优先解决字幕内容完整性、语音切点和成片复查。现有四个质量 Skill 已能表达
这些要求，但 CLI 尚未把部分要求变成可执行的检查或编辑能力。继续扩充 Skill 数量的
收益，预计低于补齐这些能力；这是依据代码差距做出的优先级判断，尚无真实素材 A/B 数据。

本轮复现了两个确定问题：长字幕被静默截断，且文字布局检查未发现内容损失；配置
`libx264` 的 `CRF=0` 会生成 `-crf 20`。前者直接影响内容完整性，后者影响指定编码参数
的正确执行。不能据此断言它们就是用户此前觉得成片不好的原因。

最值得持续跟踪的项目是 Video Timeline Copilot、video-edit-cli、dawn-cut 和
video-alchemy。Auto-Editor、WhisperX、LosslessCut 分别补充节奏参数、时间对齐和编码
边界的经验。X 用于发现案例与工作流，不用于证明成片效果或性能。

## 现状基线

以下均为当前源码证据 [T1，本地]，不以旧计划作为实现证明。

| 能力 | 当前事实 | 对输出的意义 |
|---|---|---|
| 逐词转录 | `TranscriptSegment.words` 已保存词级时间 | 可以利用现有数据；不是必须先更换 ASR |
| 初版剪辑 | `scaffold_cutlist` 按每个转录 segment 生成一个 item，直接使用段落起止；整段一条字幕 | 是时间骨架；不会自行保留自然停顿、比较重复 take 或优化字幕分句 |
| 文字布局 | `_wrapped_lines` 返回 `lines[:4]`，固定字高比例；`TextInspection` 检查边界与缺字 | 可能把“放得下”和“内容完整”混为一谈 |
| 声音 | 切机位和覆盖画面保留主音轨；master 已做测量后的两遍响度归一化 | 这两项已经具备，不应重复建设；仍缺少相同响度的试听对比流程 |
| 转场 | 当前相邻 fade 同时处理视频和音频 | 不等同于重叠溶解，也不应套用到每个语音切点 |
| 画面 | fit + padding；已有 B-roll、静态图、标题、字幕、机位切换 | 可先改善既有镜头编排；尚非主体跟踪裁切或动画合成系统 |
| 编码 | item 编码后 concat 使用 stream copy；master 响度处理继续复制视频流 | 没有证据支持“当前总是反复重编码整个视频”的诊断；master 音频会再编码 |
| QC | 流、时长、黑场、静音、响度、峰值、文字边界和切点前后图 | 技术 QC 不能判断观点完整、词头被切、语气自然或故事好看 |

关键位置：

- [初版剪辑](../../src/interview_edit/cutlist/service.py)：`scaffold_cutlist`。
- [文字排版](../../src/interview_edit/adapters/text.py)：`_wrapped_lines`、`_compose_text_image`。
- [编码参数](../../src/interview_edit/adapters/render.py)：`video_codec_args`。
- [渲染流程](../../src/interview_edit/render/service.py)：`_build_item`、`render_cutlist`。
- [QC](../../src/interview_edit/qc/service.py)：`_check_text`、`run_qc`。
- [真实素材验收清单](../tests/real-media-beta-checklist.md)：现有清单标记尚未执行，不能当作成片验收结果。

## 候选项目与可迁移做法

### 1. Video Timeline Copilot：把切点检查做成程序能力

[项目](https://github.com/ludmila-omlopes/video-timeline-copilot) [T1] 的
[audio_refine.py](https://github.com/ludmila-omlopes/video-timeline-copilot/blob/6779a4828c5107f1b4df1674377938d8eb8a7e5a/helpers/audio_refine.py)
会在现有切点附近分析音频活动，必要时向外扩展边界，并重算后续时间、输出变化报告。
[测试](https://github.com/ludmila-omlopes/video-timeline-copilot/blob/6779a4828c5107f1b4df1674377938d8eb8a7e5a/tests/test_audio_refine.py)
覆盖边界扩展、不吸入距离较远的下一段声音、时间重排。

建议借鉴“已选内容 → 边界检查 → 有依据的小幅修正”，而非让模型猜毫秒。接入时使用
现有整数微秒、代理映射和校验，不复制其浮点秒协议。它的 RMS 阈值并不理解语义；
背景音乐、气声和邻接说话人仍需限制搜索范围及人工复听。

### 2. video-edit-cli：先保留声音基线，再做等响度比较

[项目](https://github.com/computerlovetech/video-edit-cli) [T1] 与本项目的定位接近：
本地 CLI、agent 写编辑计划、执行结果留存来源。
[声音流程](https://github.com/computerlovetech/video-edit-cli/blob/d2dff7ff9d653ab88442da9ebbf9272c312af6a9/skills/video-edit-cli/references/audio-restoration.md)
要求先分析，保留只做 mastering 的版本，再决定是否降噪。
[comparison.py](https://github.com/computerlovetech/video-edit-cli/blob/d2dff7ff9d653ab88442da9ebbf9272c312af6a9/src/video_editor/audio/comparison.py)
实际生成响度匹配的试听片段和指标报告。

建议增加原声/基础处理/可选降噪的对比证据，避免把更响误认为更好。其代码按全段响度
计算增益，再截取试听片段；本项目设计时还应测量所选片段的实际响度与峰值。不要直接
照搬外部目标值或默认安装降噪模型。现有 master 两遍归一化应继续复用。

### 3. dawn-cut：字幕首先必须不丢内容

[caption.ts](https://github.com/kwakseongjae/dawn-cut/blob/7de68fce41505d8092ec227806b8d4bea4127675/packages/core/src/caption.ts)
和 [测试](https://github.com/kwakseongjae/dawn-cut/blob/7de68fce41505d8092ec227806b8d4bea4127675/packages/core/src/caption.test.ts)
[T1] 明确保护换行前后的文字完整性，超过期望行数时仍保留文本，测试也覆盖混合语言。

最适合借鉴的是“不静默丢字”的不变量。它按空格分词，单个超长词可独占一行，因此
不能直接用来解决无空格中文长句。中文仍需语义分句、标点约束、真实字体宽度测量及
新的字幕时间分配；排版溢出应明确报错或进入重新分句，而非丢弃尾部文字。

### 4. video-alchemy：每次重新剪辑，字幕和 B-roll 一起重新映射

[项目](https://github.com/kingbootoshi/video-alchemy)及
[PIPELINE.md](https://github.com/kingbootoshi/video-alchemy/blob/3c7fd6bb3cac517e1989a419c172f204277454e7/docs/PIPELINE.md)
[T1，主要为作者流程说明] 把保留片段、完整句子边界、字幕与 B-roll 时间映射连接起来，
并描述用自然语言意见反复修剪的过程。

本项目已有 keep-list 形式的 cut-list 和覆盖画面，下一步应做可靠的“修改一个源区间，
同步更新其 item、机位、字幕、overlay”的领域操作，减少手改 YAML 的错位风险。
不照搬其激进删减倾向和固定 padding；访谈、教程必须保留限定条件及步骤依赖。
作者案例不是本项目的速度或质量保证。

### 5. Auto-Editor：把节奏变成可检查、可调的参数

[当前 README](https://github.com/WyattBlue/auto-editor/blob/8db9eb0c612600644a9a63cdbbba542b661ca847/README.md)
[T1] 提供音频/运动等编辑条件、前后可不同的 margin，以及外部编辑器导出。
更适合参考其粗剪参数和时间线导出，不适合把音量阈值当作内容价值判断。

建议提供保守/标准/紧凑的候选节奏配置，但底层输出必须显式列出删改范围和原因，允许
保护情绪停顿、思考时间和演示等待。配置的数值需由中文真实素材验证，不直接复制上游默认。

### 6. WhisperX：作为可选时间对齐环节，先验证再决定

[README](https://github.com/m-bain/whisperX/blob/2cfd7b7c5c7bba144954364db747319b50e8232b/README.md)
[T1] 介绍 forced alignment 和词级时间，同时列出词典外文本、数字、重叠讲话和说话人
识别的限制，且对齐模型依赖语言。

本项目已保存词时间，优先用现有模型测边界误差；只有中文/中英混说样本证明需要，才
在 adapter 后增加可选对齐能力。对齐失败需标记未知并保留上下文，不造出看似精确的时间。
上游运行环境、中文模型质量和本机速度均未在本次调研实测。

### 7. LosslessCut：研究快速导出，但不把无损剪切设成默认答案

[smartcut.ts](https://github.com/mifi/lossless-cut/blob/5c4648fd8a79c83040f16f34fe9e503aec5d27af/src/renderer/src/smartcut.ts)
包含切点与关键帧分析；[故障文档](https://github.com/mifi/lossless-cut/blob/master/docs/troubleshooting.md)
[T1] 明确 Smart cut 是实验性功能，并非对所有文件有效。

本项目带字幕、覆盖画面、缩放的最终输出仍需要编码；不要为了快牺牲语音精确切点。
未来只对不带效果、流参数兼容的区段评估快速路径。学习算法和限制即可，复制 GPL
源码前需要单独记录许可决策。本次未复制或运行外部代码。

## X 线索如何落实

1. [Hassan 发布 SubStudio，2026-04-06](https://x.com/nutlope/status/2041199444855492790)
   [T1，作者发布；效果主张未验证] 对应
   [Nutlope/ai-subtitles](https://github.com/Nutlope/ai-subtitles)。README 描述自动合并字幕块、
   预览样式和 SRT/VTT/MP4 导出，也说明其音频转录调用 Together AI。可以借鉴交互与
   字幕组织，不能当作本地离线方案接入。README 自称 MIT，但 GitHub API 未识别许可证，
   若复制源码需进一步核对，不能只看宣传语。
2. [dotta 的脚本、品牌与 Remotion 制作实践，2026-03-26](https://x.com/dotta/status/2037206700092989789)
   [T1，作者陈述；效率主张未验证] 展示先改脚本再做视频并迭代细节。
   本次直接打开返回 403，搜索索引可读取正文摘要；没有核验视频素材本身。
   借鉴明确的 edit brief、style profile 和逐条反馈，不推导“十分钟自动完成”的承诺。
3. [Remotion 当前官方字幕文档](https://www.remotion.dev/docs/captions/) [T1，页面更新 2026-09-07]
   分开处理字幕导入、展示与导出。若以后要逐词高亮、动态图表，可作为可选后端研究；
   当前两个确定问题都不需要引入 React/Remotion 才能修复。

X 检索结果存在覆盖限制；没有检索到精确项目名的帖子，不表示该项目无人使用。

## 两个本地复现

### 长字幕损失没有进入文字检查结果

使用当前 `inspect_text_layout` 的实际排版路径，1280×720、字幕位置、5% 安全区、
系统 `STHeiti Medium.ttc` 字体。输入下面句子重复十次，共 310 个字符：

> 字幕必须保留完整语义并且不能悄悄丢失结尾的关键数字和否定条件。

在调用中记录 `_wrapped_lines` 返回值：实际保留四行、112 个字符，另外 198 个字符
没有参与绘制。检查结果仍是 `within_safe_area=True`、`missing_glyph_count=0`。
这证明布局检查没有覆盖文本损失；没有运行整条渲染/QC 链，也不把该结果说成整套 QC 通过。

修复方向：任何字幕输入必须完整保留，或者明确拒绝渲染；再用分句和多 cue 解决承载问题。
只取消四行限制仍可能遮挡画面，因此要同时给出溢出证据，不能无限向屏幕外绘制。

### 合法的零值编码配置被默认值覆盖

构造 `RenderProfile(video_codec="libx264", width=1920, height=1080,
frame_rate="25/1", crf=0)`，调用 `video_codec_args(profile, "libx264")`，返回：

```text
['-c:v', 'libx264', '-preset', 'medium', '-crf', '20']
```

原因是 `profile.crf or 20` 把合法的零值当成空值。修复应区分 `None` 与 `0`，并分别验证
默认值、零值及普通值。不建议把所有项目改成 CRF 0；该问题是参数契约错误，不是推荐预设。

## 优化顺序与验收

下表是建议实施范围，不是已存在的命令，也不是已经批准的接口变更。

| 顺序 | 工作 | 可观察验收 | 依赖/边界 |
|---|---|---|---|
| 1 | 修复字幕静默丢字、CRF 零值 | 长中文、中英混排、数字单位和结尾否定词完整；无法布局则明确失败；零值参数原样传递 | 聚焦 bug 修复，先回归用例 |
| 2 | 源区间修改与时间映射操作 | 收紧或扩展 item 后，字幕、机位、B-roll 均对准新时间；原修订可复现 | 复用整数微秒及 sync/proxy 映射 |
| 3 | 语音切点检查与候选修正 | 检出词内切点；修正不吸入下一句、不越素材边界；按相同内容试听比较 | 先使用现有词时间和本地音频活动；必要时再评估对齐模型 |
| 4 | 中文字幕分句与有限样式 | 同一文字按语义拆 cue，播速可读，字号/边距一致，导出字幕对应成片而非原片时间 | 先完整性和可读性，再逐词高亮；公共字段需更新 spec |
| 5 | 按问题时间码的局部试听/预览对比 | 一条反馈对应明确 item/join；新旧片段等响度；不同检查标记已听、已看、只测量或未知 | 利用现有 item/act 预览；边界问题必须涵盖左右相邻上下文 |
| 6 | 有条件的声音处理与 B-roll 编排 | 降噪不吞气声、不产生抽吸；B-roll 解释当前内容，覆盖时主音轨连续 | 先基线与对比，后决定是否引入模型或外部素材 |
| 7 | 竖屏构图、动态图表、动画字幕或 NLE 导出 | 画面关键文字不裁切；动画时长和字幕/语音一致；导出保留源映射 | 独立功能设计与素材基准；不先替换现有执行引擎 |

最小建议迭代：先完成第 1–4 项，并配第 5 项的局部复查手段。用同一组真实素材比较
旧版和新版，分别记录内容丢失、切坏词头/词尾、需要返工的切点、字幕拥挤及修改次数。
这是建议测量方案，不是已知的改善比例。样本至少应包含自然停顿、重复 take、中文数字、
中英混说、背景噪声及多机位中的实际常见情况；不需要一次覆盖所有创作者格式。

## 假设检验与反面证据

| 初始假设 | 判断 |
|---|---|
| 仅靠 Skill 可以解决剩余输出问题 | 否定其充分性：静默丢字和编码参数错误已复现，需要程序修复 |
| 利用已有词时间并核对切点附近音频，比直接用 segment 边界更有改进空间 | 方法与代码差距有证据；对本项目的实际收益尚未做 A/B 验证 |
| 成片不好主要因为 FFmpeg，需要更换 Remotion | 证据不足；当前明确缺陷与后端选择无关，且母版已有视频流复用 |
| 技术 QC 通过意味着可以交付好看的剪辑 | 不成立：技术指标不覆盖语义、听感和节奏；本次排版复现也暴露内容完整性检查缺口 |

反面观点与回应：

- **自动删除静音最快。** Auto-Editor 明确需要 margin，VTC 也围绕切点做活动检查；
  安静区可能是情绪或操作等待。速度不能替代保留理由。
- **dawn-cut 有 CJK 测试，直接抄换行即可。** 实际算法按空格分词，其韩文测试不证明
  无空格中文句子的阅读体验。可以借鉴不丢字约束，不能省掉中文分句和字体测量。
- **换 WhisperX 就能完全精确。** 上游明确承认对齐词典、数字、重叠讲话和语言模型限制。
  应保留失败状态，不能把强制对齐当真值。
- **无损剪切同时解决质量和速度。** LosslessCut 官方明确关键帧和 Smart cut 限制；
  带字幕合成仍需编码。快速路径只适合满足条件的素材和操作。
- **先上自动降噪更专业。** video-edit-cli 要求保留仅 mastering 的对照；降噪也可能
  损伤声音。先等响度试听，比默认启用模型更可验证。

## 来源快照与限制

读取日期均为 2026-09-08。GitHub commit 时间只用于定位快照，不视为活跃度或质量评分。
许可证列是 GitHub API 的识别结果，复制/引入前仍应检查实际文件及依赖、模型许可。

| 项目 | 快照短 SHA | 最近提交时间（UTC） | 许可字段 | 本轮深度 |
|---|---|---|---|---|
| computerlovetech/video-edit-cli | `d2dff7f` | 2026-07-19 | MIT | README、声音流程、comparison/mastering 源码 |
| kingbootoshi/video-alchemy | `3c7fd6b` | 2026-07-27 | MIT | README、PIPELINE、启动入口；未跑完整 cutter |
| ludmila-omlopes/video-timeline-copilot | `6779a48` | 2026-08-31 | MIT | 音频边界实现与测试 |
| kwakseongjae/dawn-cut | `7de68fc` | 2026-07-10 | MIT | 字幕换行实现与测试 |
| WyattBlue/auto-editor | `8db9eb0` | 2026-09-07 | Unlicense | 当前 README；音频源码仅下载，未据此主张性能 |
| mifi/lossless-cut | `5c4648f` | 2026-09-07 | GPL-2.0 | Smart cut 实现与官方限制 |
| m-bain/whisperX | `2cfd7b7` | 2026-07-13 | BSD-2-Clause | 当前 README 与对齐限制 |
| Nutlope/ai-subtitles | `261c50e` | 2026-04-07 | 未识别 | X 发布、README、仓库元数据；未审阅完整实现 |

没有运行这些外部项目，不能提供跨项目速度、识别准确率或视觉效果排名。没有查看用户
此前不满意的成片，本报告给出的是代码缺陷、可迁移方法和优先级，不是该成片的根因诊断。
临时源码下载与复现记录留在系统临时目录，未作为仓库资产引入。
