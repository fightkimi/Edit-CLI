# 剪辑输出质量 Skills：筛选与接入记录

本次接入三个开源 Skill 的项目适配版，以及一个原创的渲染审查 Skill。重点是让每次剪辑
落实脚本结构、自然切点、中文字幕可读性、声音与画面复查，而不是只增加提示词数量。
这次不修改渲染引擎；真实成片改善仍需同素材、同片段的前后对比。

## 来源与决策

| 候选 | 固定快照 | 决策 |
|---|---|---|
| [ECC video-editing](https://github.com/affaan-m/everything-claude-code/tree/e04ea0b9cc8248686edf5ac751cadff550e162b8/skills/video-editing) | `e04ea0b9cc8248686edf5ac751cadff550e162b8` | MIT；适配为 `edit-story-structure`，保留结构先于包装、编辑决策显式化 |
| [Video Timeline Copilot](https://github.com/ludmila-omlopes/video-timeline-copilot/tree/6779a4828c5107f1b4df1674377938d8eb8a7e5a) | `6779a4828c5107f1b4df1674377938d8eb8a7e5a` | MIT；适配为 `edit-speech-pacing`，保留完整语句、切点复听、重复 take 和结尾完整性 |
| [6missedcalls video-editing-skill](https://github.com/6missedcalls/video-editing-skill/tree/7dc6e1da66f43eff44c3692d4b84e06aef6590b6) | `7dc6e1da66f43eff44c3692d4b84e06aef6590b6` | MIT；适配为 `edit-caption-audio-review`，收窄为现有字幕与声音能力的编排和复查 |
| [Remotion 官方 Skills](https://github.com/remotion-dev/skills/tree/f54682712abc4a68cdc7c41513bd3b3298829873) | `f54682712abc4a68cdc7c41513bd3b3298829873` | GitHub license 字段为空，目录中未发现许可证；仅链接参考，不复制、不运行 |
| [ECC remotion-video-creation](https://github.com/affaan-m/everything-claude-code/tree/e04ea0b9cc8248686edf5ac751cadff550e162b8/skills/remotion-video-creation) | 同 ECC 快照 | 已下载审阅，现有项目没有 Remotion 后端，未安装；不通过镜像转引官方内容规避许可不明 |

各适配版的 `SOURCE.json` 记录原始文件路径、commit、原文件 SHA-256；`LICENSE.upstream`
保留上游完整 MIT 文本。只安装经适配的指引，不将上游媒体处理脚本或整个仓库放入项目。
下载使用 skill-installer 的固定版本安装流程，先进入临时审阅目录，再筛选适配。

## X 线索

- [William Candillon 的 Remotion 作品讨论](https://x.com/wcandillon/status/2015345960491069718)
  引用了官方 Agent Skills 发布，可用于找到上游入口。
- [dotta 的视频制作实践](https://x.com/dotta/status/2037206700092989789)
  将脚本修改、品牌参考和视频制作分开，且明确还有细节需要迭代。

这些是实践线索，不是本项目的质量证据。未据此承诺留存率、爆款效果或特定节省时间。

## 与现有 CLI 的对齐

- 外部 EDL、浮点秒、`vtc`、独立 FFmpeg、Remotion、云服务流程改为现有整数微秒 cut-list
  和 CLI；源媒体只读，工作产物留在配置的 artifact root。
- 先选择叙事，再精修边界，再按新时间生成字幕，最后评审画面；主 Skill 按问题按需加载。
- 切点应保护可听见的词头词尾；转录时间不是音素真值。无法听到预览时应报告未验证。
- 当前 renderer 使用 fit + padding，字幕以本地字体绘制；不把自动裁切、逐词动画字幕、
  任意位置样式、LUT、音乐 ducking 或 J/L cut 当成已有选项。
- 当前淡入淡出同时影响画面与声音，不能把它当作无损修复所有跳剪的通用办法。
- preview 使用代理且默认低于 master 分辨率；不能把预览清晰度直接等同母版清晰度。
- 原创 `edit-render-review` 将这些实现事实转成症状、证据和可执行修正的审查表。

## 验证边界

基线 Ruff、mypy 和 108 项测试通过，包括合成渲染与创作者格式流程。最终检查结果记录在
[接入验证](../tests/output-quality-skills-integration.md)。静态 Skill 校验只能证明结构和引用，
合成测试证明现有执行流程没有回归；均不能替代真实视频的叙事、听感、字幕和画面 A/B 评审。
