# Interview Edit CLI + Codex Skill
## V1 产品需求、技术规格与执行交接

文档状态：拟定基线
日期：2026-09-03
暂定项目名：`interview-edit`
暂定 CLI 命令：`interview-edit`
暂定 Skill 名称：`interview-edit`

参考项目：

- https://github.com/guang-tech/interview-edit-pipeline
- 分析基线提交：`95c0a93dbf3c9823317b459ad06b86bcf3a0e029`
- 原项目仅作为方法论和功能参考，不作为新工具的运行时依赖。

---

# 1. 项目结论

开发一个本地优先的访谈视频剪辑工具，以两部分交付：

1. `interview-edit` CLI
   负责素材索引、代理生成、转录、机位同步、cut-list 校验、渲染、质检和版本冻结。

2. Codex Skill
   负责理解用户的自然语言剪辑要求，调用 CLI、阅读转录稿和质检证据、生成或修改 cut-list，并向用户汇报结果。

核心原则：

- CLI 是唯一执行内核和事实来源。
- Skill 不重复实现剪辑逻辑。
- 不让 Codex 临时拼接未经验证的 FFmpeg 命令。
- 原始素材只读，永不覆盖。
- 默认在本地运行 FFmpeg、FFprobe 和转录模型。
- 大文件不直接塞给 Codex；Codex主要读取转录稿、媒体索引、缩略图、contact sheet 和 QC 报告。
- 所有操作可复现、可中断恢复、可审计、可版本化。
- V1 不做 GUI，不做 MCP，不替代 Premiere、Final Cut 或 DaVinci Resolve。

---

# 2. 已验证的现状

原项目已经提供了较完整的实战方法：

- cut-list 驱动剪辑。
- FFmpeg 渲染。
- faster-whisper 本地转录。
- 多机位音频同步。
- 字幕、B-roll、转场和 L-cut。
- 黑场、静音、切点截图等质量检查。
- 成片版本冻结。

但原项目当前更接近“某个具体项目的脚本模板”，不能直接作为通用产品：

- 项目路径、素材路径、CUDA、NVENC 等写死在脚本中。
- 配置、业务数据和执行逻辑混在一起。
- 缺少依赖清单、自动化测试和 CI。
- cut-list 校验失败时不一定返回失败状态。
- 多窗口同步、逐帧确认等文档承诺尚未完整落实。
- 部分脚本名义上支持分段渲染，实际会重新渲染整个章节。
- 版本冻结没有完整记录输入指纹、配置哈希、软件版本和输出校验值。
- 主要面向 Windows + NVIDIA，当前不适合直接在 macOS Codex 环境运行。

因此新项目应迁移“方法和数据模型”，不应简单包装现有脚本。

---

# 3. 产品目标

## 3.1 用户目标

用户可以把本地访谈素材目录交给 Codex，然后使用自然语言完成如下工作：

- “扫描这批三机位访谈素材。”
- “生成代理和转录稿。”
- “同步三个机位。”
- “根据转录稿整理一个 8 分钟人物短片。”
- “删除重复表达和明显口误。”
- “在这段回答中切到侧机位。”
- “生成低清预览。”
- “检查黑场、静音、字幕和音量。”
- “确认后输出母版并冻结为 v1。”

## 3.2 成功标准

V1 完成后应满足：

- CLI 安装后可以从源码目录以外直接调用。
- 素材可以位于本地任意授权目录，不要求复制进代码仓库。
- 原始素材在完整流程前后保持不变。
- 每一步都能单独运行和重复运行。
- 同样的输入、配置和工具版本可以得到可追溯的结果。
- 中断长时间任务后可以继续，而不是从头开始。
- cut-list 不合法时必须在渲染前失败。
- 修改一个片段时，只使相关缓存失效。
- 未通过 release QC 时不得冻结正式版本。
- Codex 能通过 Skill 稳定选择正确命令，而不是猜测命令。
- 没有 Codex 时，CLI 仍然可以独立工作。

---

# 4. 目标用户

V1 主要面向：

- 独立内容创作者。
- 访谈纪录片导演或剪辑师。
- 有基础命令行能力的内容团队。
- 希望通过 Codex 操作本地素材的非专业剪辑用户。

V1 优先场景：

- 单人或双人访谈。
- 固定机位、多机位拍摄。
- 中文为主，可包含少量英文。
- 一条主采访音轨，其他机位作为替代画面。
- 最终输出横版人物访谈或纪录片短片。

---

# 5. 范围

## 5.1 V1 范围内

- 项目初始化和环境检查。
- 本地素材扫描、索引和变更检测。
- 媒体元数据提取。
- 代理视频、音频代理、缩略图和 contact sheet。
- 本地语音转录。
- 用户词典和转录文本纠错。
- 多机位音频同步。
- 同步漂移检测和人工校正。
- cut-list 数据结构。
- cut-list 创建、查看和严格校验。
- 采访片段、机位切换、B-roll、静帧、字幕和基础转场。
- 章节或片段级预览渲染。
- 最终母版渲染。
- 黑场、静音、音量、流参数、素材越界和重复使用检查。
- 质检证据输出。
- 版本冻结和完整运行清单。
- Codex 项目级 Skill。
- 合成测试素材和端到端测试。

## 5.2 V1 明确不做

- 图形化时间线编辑器。
- 云端素材存储或上传。
- 实时协作。
- 生成式视频和生成式 B-roll。
- 自动替代人的最终审美判断。
- Premiere、FCP、Resolve 工程文件导出。
- 直播或实时剪辑。
- 通用电影、综艺、音乐视频剪辑。
- 对外公开的 MCP 服务。
- Codex Plugin 商店分发。

Skill 完成稳定验证后，才考虑打包成 Plugin。官方建议先用 Skill 固化工作流，再在需要多人安装时打包为 Plugin。[Codex Skill 文档](https://learn.chatgpt.com/docs/build-skills)

---

# 6. 推荐技术方案

## 6.1 技术栈

推荐默认值：

- Python 3.11+
- `uv`：依赖和虚拟环境管理
- Typer：CLI
- Pydantic v2：配置和数据校验
- FFmpeg / FFprobe：媒体处理
- pytest：测试
- Ruff：格式和静态检查
- mypy 或 pyright：类型检查
- YAML：项目配置与人工可编辑的 cut-list
- JSON / JSONL：机器输出、索引、转录和运行清单

转录后端必须通过适配器隔离：

```text
Transcriber
├── FasterWhisperTranscriber
├── MlxWhisperTranscriber（候选）
└── MockTranscriber（测试）
```

M0 阶段需要根据开发机硬件实测确定：

- Apple Silicon 优先后端。
- NVIDIA CUDA 优先后端。
- CPU fallback。
- 模型下载、缓存位置和离线运行行为。

## 6.2 架构分层

```text
用户自然语言
      ↓
Codex Skill
      ↓
interview-edit CLI
      ↓
领域服务
├── ingest
├── proxy
├── transcribe
├── sync
├── cutlist
├── render
├── qc
└── version
      ↓
本地适配器
├── filesystem
├── ffmpeg / ffprobe
└── whisper backend
      ↓
本地素材（只读）与项目产物（可写）
```

约束：

- CLI 层只解析参数和组织输出。
- 领域逻辑必须可以脱离 CLI 进行单元测试。
- FFmpeg、Whisper 和文件系统操作都通过适配器封装。
- 禁止在 import 时自动开始处理。
- 调用外部程序必须使用参数数组，禁止拼接 shell 字符串。
- CLI 本身不调用 OpenAI API。
- Codex 通过当前会话完成语义分析和 cut-list 编辑。

---

# 7. 推荐仓库结构

```text
interview-edit/
├── pyproject.toml
├── README.md
├── AGENTS.md
├── src/
│   └── interview_edit/
│       ├── cli/
│       ├── config/
│       ├── models/
│       ├── ingest/
│       ├── proxy/
│       ├── transcribe/
│       ├── sync/
│       ├── cutlist/
│       ├── render/
│       ├── qc/
│       ├── versioning/
│       └── adapters/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
├── examples/
│   └── minimal-interview/
├── docs/
│   ├── prds/
│   ├── specs/
│   ├── plans/
│   ├── tests/
│   └── decisions/
└── .agents/
    └── skills/
        └── interview-edit/
            ├── SKILL.md
            ├── agents/
            │   └── openai.yaml
            └── references/
                ├── cli-reference.md
                ├── cutlist-schema.md
                ├── qc-policy.md
                └── privacy.md
```

项目级 Skill 放在 `$REPO_ROOT/.agents/skills/interview-edit/`。Codex 支持通过 `$interview-edit` 显式调用，也可以根据 Skill 的 description 自动匹配。[Codex Skill 位置与触发规则](https://learn.chatgpt.com/docs/build-skills)

---

# 8. 用户剪辑项目目录

代码仓库与具体剪辑项目必须分离。

```text
my-interview-project/
├── interview-edit.yaml
├── cutlists/
│   ├── main.yaml
│   └── revisions/
├── dictionaries/
│   └── corrections.yaml
├── artifacts/
│   ├── index/
│   ├── proxies/
│   ├── audio/
│   ├── transcripts/
│   ├── contact-sheets/
│   ├── sync/
│   ├── renders/
│   ├── qc/
│   ├── versions/
│   └── logs/
└── .interview-edit/
    ├── state.json
    └── cache/
```

原始视频可以位于其他目录：

```yaml
media_roots:
  - /Volumes/InterviewSSD/Project-A
```

规则：

- 默认不复制原始素材。
- 素材路径只出现在索引和 manifest 中。
- `artifacts` 不得位于原始素材目录内部。
- 所有生成文件写入项目输出目录。
- 原始素材目录按只读方式使用。
- 需要提供“复制代理但不复制原片”的可选工作流。

---

# 9. 核心数据模型

## 9.1 ProjectConfig

至少包含：

- `schema_version`
- `project_id`
- `name`
- `media_roots`
- `artifact_root`
- `privacy_mode`
- `language`
- `timeline`
- `transcription`
- `sync`
- `render_profiles`
- `audio_targets`
- `fonts`
- `safety`

配置优先级：

```text
命令行参数
> 环境变量 INTERVIEW_EDIT_*
> 项目配置
> 用户配置
> 系统默认值
```

## 9.2 MediaAsset

每个素材使用稳定 ID，不使用文件名作为唯一标识。

字段至少包括：

- `asset_id`
- `canonical_path`
- `relative_path`
- `size`
- `mtime`
- `fingerprint`
- `full_hash`，可选
- `duration_us`
- `stream_time_base`
- `video_stream`
- `audio_streams`
- `camera_id`
- `take_id`
- `capture_time`
- `probe_version`

## 9.3 时间表示

禁止使用无类型的浮点秒数作为持久化剪辑时间。

推荐：

- 持久化使用整数微秒 `*_us`。
- 同时保存源流 `time_base`。
- 项目时间线使用有理数帧率，例如 `25/1`、`30000/1001`。
- 对用户显示 SMPTE timecode。
- 允许用户输入 timecode、秒数或帧号，但保存时必须标准化。
- VFR 素材通过真实 PTS 映射，不假设恒定源帧率。

## 9.4 CutList

必须版本化并通过正式 schema 校验。

核心结构：

- `schema_version`
- `project_id`
- `timeline`
- `acts`
- `items`
- `subtitle_policy`
- `render_profile`

每个 item 至少包含：

- `item_id`
- `kind`
- `source_id`
- `source_in_us`
- `source_out_us`
- `timeline_duration_us`
- `audio_source`
- `base_camera`
- `camera_cuts`
- `overlays`
- `subtitles`
- `transition_in`
- `transition_out`
- `notes`

V1 支持的 `kind`：

- `interview`
- `broll`
- `still`
- `title`
- `transition`

## 9.5 RunManifest

每次长任务创建唯一 `run_id`，记录：

- 命令及标准化参数。
- 开始、结束和状态。
- 项目配置哈希。
- cut-list 哈希。
- 输入素材指纹。
- FFmpeg、FFprobe、Python 和转录模型版本。
- 当前代码 Git commit。
- 环境和硬件摘要。
- 输出路径、大小和校验值。
- 警告与错误。
- 父 run。
- 缓存命中情况。

V1 的 `proxy build`、`transcribe` 与 `sync` 使用统一的本地 operation-run 清单；`render` 使用
包含完整 FFmpeg 参数的专用 render-run 清单，`qc` 使用独立 report ID。为避免隐私泄露和
重复大文件 I/O，operation-run 只校验小型控制产物，不写入转录正文、原始 stderr 或大型
媒体 payload。

## 9.6 QCReport

每条问题包含：

- `severity`
- `code`
- `message`
- `item_id`
- `timeline_time_us`
- `source_id`
- `evidence_path`
- `suggested_action`

严重级别：

- `info`
- `warning`
- `error`
- `blocking`

---

# 10. 产物依赖关系

```text
本地原始素材（只读）
    ↓
媒体索引
    ├── 代理 / contact sheet
    ├── 转录稿
    └── 多机位同步结果
            ↓
         cut-list
            ↓
        渲染 run
            ↓
         QC 报告
            ↓
        冻结版本
```

产物是否过期由输入哈希决定，不使用模糊的全局“完成”状态。

例如：

- 原片变化：索引及所有下游产物失效。
- 转录配置变化：只使相关转录和依赖转录的建议失效。
- 一个 cut-list item 变化：只使该 item 和后续拼接产物失效。
- 字体变化：字幕相关片段失效。
- FFmpeg 版本变化：必须记录，并允许用户选择是否重新渲染。

---

# 11. CLI 设计

## 11.1 全局参数

```text
--project PATH
--json
--quiet, -q
--dry-run, -n
--force, -f
--no-color
--help, -h
--version
```

行为约束：

- 人类可读结果默认输出。
- `--json` 输出稳定的机器协议。
- 进度、提示和装饰信息写入 stderr。
- 机器数据写入 stdout。
- V1 命令均为非交互式；需要授权的动作必须通过显式参数或会话确认，不能临时弹出隐式询问。
- 破坏性操作在非交互环境中必须显式传入 `--force`。
- 大量内容写入文件，只在 stdout 返回摘要和路径。

## 11.2 命令面

```text
interview-edit init
interview-edit doctor
interview-edit status

interview-edit ingest
interview-edit proxy build
interview-edit transcribe
interview-edit sync

interview-edit cutlist scaffold
interview-edit cutlist inspect
interview-edit cutlist validate

interview-edit render
interview-edit qc

interview-edit version freeze
interview-edit version list
interview-edit version show
interview-edit version verify
```

## 11.3 关键命令

### `init`

```text
interview-edit init \
  --project PATH \
  --name NAME \
  --media-root PATH \
  --privacy strict|assisted
```

要求：

- 生成项目配置和目录。
- 不覆盖已有配置，除非显式 `--force`。
- 非交互模式下必须明确指定 privacy。
- 检查输出目录没有落在原始素材目录内。

### `doctor`

检查：

- FFmpeg 和 FFprobe。
- 编解码器。
- 转录后端和模型。
- CPU、GPU 和可用加速。
- 字体。
- 磁盘空间。
- 素材读取权限。
- 输出写入权限。
- Skill 是否可被 Codex发现。
- 当前平台支持状态。

不得默认下载或安装依赖。

### `ingest`

关键参数：

```text
--media-root PATH
--camera-map FILE
--extensions LIST
--full-hash
--build-proxies
--resume
```

要求：

- 支持递归扫描。
- 排除项目产物目录。
- 处理 Unicode、空格和中文路径。
- 明确定义符号链接策略。
- 使用快速指纹检测变化。
- 可选完整哈希。
- 重复执行时不得产生重复资产。
- 不加载完整视频到内存。

### `proxy build`

生成：

- 低码率代理。
- WAV 或其他标准化音频代理。
- 缩略图。
- contact sheet。
- 时间码映射。

代理必须保持与原片可映射的时间轴。

### `transcribe`

关键参数：

```text
--asset ID
--take ID
--language zh
--model MODEL
--device auto|cpu|cuda|metal
--resume
```

要求：

- 默认本地推理。
- 分段写入，支持恢复。
- 保存 segment 和 word timestamps。
- 保存原始识别结果，纠错另存为独立层。
- 模型、设备、参数和输入指纹进入缓存键。
- 不允许在没有显式许可时上传音频。

### `sync`

关键参数：

```text
--take ID
--reference-camera ID
--window-count N
--visual-check
--manual-offset CAMERA=VALUE
```

要求：

- 至少使用开头、中部、结尾多个窗口。
- 检测固定偏移和随时间漂移。
- 输出 offset、drift、confidence 和证据。
- 生成可供人工复核的同步截图或短代理片段。
- 置信度不足时不得静默标记为成功。
- 支持人工 offset 覆盖，并记录来源。

### `cutlist scaffold`

生成空白或基于转录结构的 cut-list 骨架。

限制：

- CLI 只生成确定性骨架。
- 叙事选择由用户或 Codex Skill 完成。
- 不在 CLI 内隐藏调用语言模型。

### `cutlist validate`

必须检查：

- schema。
- ID 唯一性。
- 素材是否存在。
- 入点、出点和素材时长。
- item 是否为正时长。
- 机位切换是否越界。
- 字幕是否越界或冲突。
- overlay/B-roll 是否重复或重叠。
- 字体和图像资产是否存在。
- 转场是否满足最小时长。
- 输出参数是否兼容拼接。
- 所需同步信息是否存在。

失败时必须返回非零退出码，且不得继续渲染。

### `render`

关键参数：

```text
--cutlist PATH
--act ID
--item ID
--profile preview|master
--output PATH
--resume
```

要求：

- 支持全片、章节和单 item。
- preview 与 master 使用不同配置。
- item 级缓存。
- 原子写入：先写临时文件，成功后替换目标。
- 失败不得删除最后一个成功版本。
- 音频默认来自配置的主音轨。
- GPU 不可用时提供 CPU fallback。
- master 默认进行两遍 loudnorm 或等效可验证流程。
- 记录实际 FFmpeg 参数和版本。
- 中断后 run 状态为 `interrupted`，不得留下伪成功产物。

### `qc`

至少包括：

- 黑场检测。
- 静音检测。
- 音量和 true peak。
- 视频流参数。
- 音频流参数。
- 画面尺寸、帧率、色彩信息。
- A/V 时长差异。
- cut-list 与输出总时长差异。
- 重复 B-roll 或素材区间。
- 素材越界。
- 切点前后证据截图。
- 字幕安全区和缺字检查。
- 冻结所需文件完整性。

支持两种策略：

- `preview`：允许 warning。
- `release`：blocking 和 error 必须为零。

### `version freeze`

要求：

- 只能冻结已成功完成且通过 release QC 的 run。
- 复制或硬链接最终产物到不可变版本目录。
- 保存 manifest、cut-list、配置、QC 报告和输出校验值。
- 默认不复制原始媒体。
- 禁止以“缺少部分文件”的状态冻结。
- `--force` 只允许覆盖非质量类限制，并必须记录原因；不得绕过素材损坏或产物缺失。

---

# 12. JSON 输出协议

所有命令的 `--json` 输出使用统一 envelope：

```json
{
  "schemaVersion": "1",
  "ok": true,
  "command": "ingest",
  "runId": "run_...",
  "data": {},
  "warnings": [],
  "artifacts": [],
  "next": []
}
```

约束：

- stdout 中只有 JSON。
- JSON 模式下不得混入进度条或 ANSI 颜色。
- 大型转录稿和 QC 证据保存到文件。
- `artifacts` 返回绝对路径或相对项目根目录的标准化路径。
- `next` 提供推荐的下一条 CLI 命令。
- 协议变更需要增加 `schemaVersion`。

退出码：

| 退出码 | 含义 |
|---:|---|
| 0 | 成功 |
| 1 | 通用运行失败 |
| 2 | 参数、配置或 schema 错误 |
| 3 | preflight 或 QC 未通过 |
| 4 | 缺少外部依赖 |
| 5 | 权限或路径边界错误 |
| 130 | 用户中断 |

---

# 13. Codex Skill 需求

Skill 路径：

```text
.agents/skills/interview-edit/SKILL.md
```

## 13.1 触发范围

应该触发：

- 用户要求扫描本地访谈素材。
- 用户要求转录、同步、剪辑、生成 cut-list。
- 用户要求渲染访谈预览或母版。
- 用户要求检查或冻结访谈成片。

不应该触发：

- 普通视频播放器问题。
- 图片生成。
- 在线视频下载。
- 非访谈类复杂影视后期。
- 用户只询问 FFmpeg 知识而不要求操作项目。

## 13.2 Skill 工作流

Skill 必须遵守：

1. 先定位项目并运行 `doctor` 或 `status`。
2. 在生成剪辑方案前确认索引、转录和同步产物是否有效。
3. 只读取完成任务所需的转录片段和视觉证据。
4. 将叙事决策写入 cut-list。
5. 每次修改后先执行 `cutlist validate`。
6. 默认先渲染 preview。
7. 阅读 QC JSON 和关键证据图。
8. 向用户说明发现的问题和建议修改。
9. 用户确认后才运行 master 渲染。
10. release QC 通过后才能冻结版本。

Skill 不得：

- 修改原始媒体。
- 绕过 cut-list 校验。
- 自己实现 FFmpeg 拼接逻辑。
- 未经许可下载模型或上传素材。
- 因 CLI 缺少能力而临时编写不可追踪的替代脚本。
- 为了通过检查而降低 QC 标准。

## 13.3 隐私模式

### `strict`

- Codex 只读取文件路径、哈希、时长、状态和统计。
- 不读取完整转录稿、缩略图或代理画面。
- 用户需要明确提供剪辑区间或自行编辑 cut-list。
- 适用于高度敏感素材。

### `assisted`

- Codex 可以读取转录稿。
- 可以读取选定的缩略图、contact sheet 和 QC 证据。
- 原始视频仍由本地 CLI 处理，不直接作为模型输入。
- 应清楚提示：被 Codex 读取的文本或图片可能进入当前模型会话上下文。

`init` 时必须明确选择一种模式，不设置隐藏默认值。

---

# 14. 安全与权限

- 所有原始素材以只读方式访问。
- 项目启动和完成时可选记录原片指纹，证明未被修改。
- 所有路径先 canonicalize，再进行边界校验。
- 阻止 `../` 等路径穿越。
- 明确定义符号链接是否允许跨出 media root。
- 外部命令禁止使用 `shell=True`。
- 文件替换使用临时文件和原子 rename。
- 日志默认不记录完整转录正文。
- 支持路径脱敏输出。
- 删除缓存属于破坏性操作，V1 可以暂不提供。
- 不自动访问网络。
- 模型或依赖下载必须显式确认。
- 在 Codex 沙箱中访问工作区外素材时，可能需要用户批准或配置额外路径权限；CLI 应在 `doctor` 阶段提前发现，而不是渲染中途失败。[Codex 沙箱说明](https://learn.chatgpt.com/docs/sandboxing)

---

# 15. 非功能需求

## 15.1 可恢复性

- 长任务分阶段提交状态。
- Ctrl+C 后保留已完成的有效分段。
- 再次运行 `--resume` 可以继续。
- 失败不得把旧的成功产物标记为过期或删除。

## 15.2 可复现性

- 固定输入、配置、cut-list 和工具版本时，结果应可重复生成。
- 不同 FFmpeg 或模型版本不承诺字节完全一致，但必须在 manifest 中暴露差异。
- 缓存键必须包含所有影响输出的参数。

## 15.3 性能

- 支持数百 GB 项目，不要求把素材复制到项目目录。
- 扫描和索引必须流式完成。
- 代理、转录、同步和渲染按素材或片段缓存。
- 修改一个 item 不得无条件重渲染整片。
- 渲染前估算磁盘空间。
- 性能结果按测试硬件记录，不先设脱离硬件的绝对速度承诺。

## 15.4 跨平台

V1 推荐：

- 首先完整验证 macOS。
- 架构上保留 Windows 和 Linux 支持。
- 禁止在领域代码中写死盘符、CUDA、NVENC 或路径分隔符。
- 加速器和编码器通过 capability detection 选择。

## 15.5 可观测性

- 长任务开始后立即显示进度。
- 每个 run 有独立日志。
- 用户能够查询当前阶段、已完成数量、失败项目和下一步。
- render 与 QC 运行清单记录底层参数数组，但不记录完整转录正文。

---

# 16. 验收标准

必须准备一套可提交仓库的合成测试素材，至少包含：

- 3 个机位。
- 2 个 take。
- 已知机位偏移。
- 一段模拟时间漂移。
- 一段静音。
- 一段黑场。
- 一处音视频参数不一致。
- 一段可重复引用的 B-roll。
- 中文和英文混合语音。
- 带空格和中文字符的路径。

必须通过以下验收：

1. 在源码目录外执行 `command -v interview-edit` 成功。
2. `interview-edit --help` 清楚说明命令结构。
3. `doctor` 能识别缺失依赖和权限问题。
4. `ingest` 重复执行不产生重复资产。
5. 原片变化后只使正确的下游产物失效。
6. 转录被中断后可以恢复。
7. 已知同步偏移的误差不超过一个项目输出帧。
8. 同步漂移能被检测或明确标记为不确定。
9. 非法 cut-list 返回退出码 3，且不产生渲染文件。
10. 单 item 修改只使相关缓存失效。
11. 渲染中断不破坏上一份成功结果。
12. QC 能发现测试素材中的黑场、静音、参数错误和重复素材。
13. release QC 未通过时禁止冻结。
14. 冻结版本包含完整 manifest、配置、cut-list、QC 和校验值。
15. `version verify` 能发现被冻结文件被修改。
16. 完整流程前后原始媒体指纹不变。
17. `--json` 输出可被程序解析且不混入终端装饰信息。
18. Skill 能针对测试提示选择正确命令顺序。
19. Skill 不会在未确认时直接进行 master 渲染或冻结。
20. CLI 能在不启动 Codex 的情况下完成完整确定性流程。

---

# 17. 测试策略

## 单元测试

覆盖：

- 配置优先级。
- 路径边界。
- 时间和 timecode 转换。
- cut-list schema。
- 素材越界和重叠判断。
- 缓存键。
- 失效传播。
- JSON envelope。
- 退出码。
- manifest。
- QC 规则。

## 集成测试

覆盖：

- FFprobe 媒体索引。
- FFmpeg 代理生成。
- 分段渲染。
- 拼接兼容性。
- loudnorm。
- 截图和黑场、静音检测。
- 外部进程中断。
- 临时文件恢复。

## 端到端测试

使用合成素材运行：

```text
init
→ doctor
→ ingest
→ proxy
→ transcribe
→ sync
→ cutlist validate
→ render preview
→ qc
→ render master
→ qc release
→ version freeze
→ version verify
```

## Skill 测试

至少建立五组测试提示：

- 只扫描，不修改。
- 根据转录稿生成初版 cut-list。
- 修改指定段落并重渲染。
- 分析 QC 失败。
- 用户确认后输出并冻结正式版本。

每组测试记录：

- 期望调用的 CLI 命令。
- 不应调用的命令。
- 是否需要用户确认。
- Skill 最终应返回的摘要。

---

# 18. 开发里程碑

## M0：项目建立与技术验证

交付：

- 新仓库和基础文档。
- 确定项目名、许可证和源码复用边界。
- FFmpeg 能力检测实验。
- macOS 转录后端实验。
- 10～30 秒合成素材。
- CLI 命令面评审。
- cut-list schema 草案。
- 关键 ADR。

完成条件：

- 能证明目标开发机上 FFmpeg 和至少一个本地转录后端可运行。
- 未开始大规模迁移旧脚本。

## M1：CLI 基础

交付：

- Python 包。
- 可安装的 `interview-edit` 命令。
- `init`、`doctor`、`status`。
- 配置模型。
- JSON 协议。
- 统一错误和退出码。
- 基础 CI。

## M2：素材和代理

交付：

- `ingest`。
- 媒体索引。
- 素材指纹。
- 代理、音频代理、缩略图和 contact sheet。
- 缓存和中断恢复。

## M3：转录和同步

交付：

- 转录适配器。
- 增量转录。
- 纠错层。
- 多窗口同步。
- 漂移检测。
- 同步证据。

## M4：Cut-list 和渲染

交付：

- 正式 cut-list schema。
- scaffold、inspect、validate。
- item 级渲染。
- 机位切换。
- B-roll、字幕和基础转场。
- preview/master profile。

## M5：QC 和版本冻结

交付：

- 自动 QC。
- 质检证据。
- release gate。
- manifest。
- freeze、list、show、verify。

## M6：Codex Skill 和 Beta 验收

交付：

- 项目级 Skill。
- Skill references。
- Skill validation。
- 自然语言端到端测试。
- 安装说明。
- 跨目录调用验证。
- 完整合成素材验收报告。

---

# 19. 关键风险

| 风险 | 处理 |
|---|---|
| 自动剪辑叙事质量不稳定 | Codex 只生成可审阅 cut-list，默认 preview-first |
| 转录错误影响剪辑 | 原始转录与纠错层分离；词典可版本化 |
| 多机位存在漂移 | 多窗口测量，不只计算单点 offset |
| VFR 导致切点不准 | 使用 PTS/time_base，不持久化裸浮点秒 |
| 硬件差异 | 适配器和 capability detection，CPU fallback |
| 缓存错误导致旧片段混入 | 缓存键包含输入、配置、工具和 cut-list 哈希 |
| 大项目磁盘爆满 | 渲染前估算空间，代理和缓存可统计 |
| 原片误修改 | 只读访问、输出边界、前后指纹验证 |
| 敏感访谈进入模型上下文 | strict/assisted 模式，最小化读取 |
| 旧项目问题被直接复制 | 按能力重新实现并用测试约束，不机械搬运 |
| 项目演变成通用 NLE | 严格限制 V1 为固定机位访谈流程 |

---

# 20. 待确认决策

新 Session 应先确认会影响架构的少量决策，其余按推荐值推进。

| 决策 | 推荐默认值 |
|---|---|
| 项目/CLI 名称 | `interview-edit` |
| 开发语言 | Python 3.11+ |
| 包管理 | `uv` |
| 首个平台 | macOS，兼容性架构覆盖 Windows/Linux |
| 首个硬件目标 | 当前开发机实测决定 |
| 转录后端 | 通过 M0 spike 选择，保留适配器 |
| 配置格式 | YAML |
| 机器输出 | JSON/JSONL |
| 时间持久化 | 整数微秒 + stream time_base |
| 原片位置 | 项目外部，只读 |
| 隐私模式 | 初始化时强制选择 |
| 默认工作流 | preview-first |
| 母版音量目标 | 作为 render profile 配置，不写死 |
| 旧仓库代码复用 | 确认组织授权和许可证后再复制 |
| Skill 分发 | V1 放在仓库 `.agents/skills` |
| Plugin/MCP | V1 之后评估 |

---

# 21. 新 Session 执行合同

## 目标

创建全新的 `interview-edit` 仓库，并在确认 M0 决策后实现 M1。不得在原项目上直接继续堆叠脚本。

## 允许写入

- 新项目仓库。
- 新项目测试 fixture。
- 新项目内部的临时测试产物。

## 只读范围

- `guang-tech/interview-edit-pipeline` 原项目。
- 用户真实采访素材。
- 用户未明确授权修改的其他目录。

## 冻结的产品边界

未经用户确认，不得改变：

- CLI 是执行内核、Skill 是编排层。
- 原片只读。
- local-first。
- preview-first。
- cut-list 驱动。
- 校验失败禁止渲染。
- release QC 失败禁止冻结。
- V1 不做 GUI、MCP 或云端素材处理。

## 首轮有序任务

| ID | 任务 | 产物 | 验证 |
|---|---|---|---|
| T1 | 检查新仓库和开发机环境 | 环境基线 | 记录 Python、FFmpeg、平台和 Git 状态 |
| T2 | 写入本 PRD | `docs/prds/interview-edit-cli-skill-v1.md` | 文档可被新任务读取 |
| T3 | 完成 M0 决策和技术 spike | ADR、实验结果 | 实际运行 FFmpeg 和本地转录 |
| T4 | 冻结 CLI 命令面和 schema v1 草案 | spec 文件 | 示例命令和 JSON 可评审 |
| T5 | 建立 Python 包和测试骨架 | `pyproject.toml`、`src`、`tests` | lint、typecheck、test 可运行 |
| T6 | 实现 `init`、`doctor`、`status` | M1 CLI | 单元和集成测试 |
| T7 | 创建 Skill 骨架 | `.agents/skills/interview-edit` | Skill 校验通过 |
| T8 | 从源码目录外验证安装 | 验收记录 | `command -v`、`--help`、`doctor` 成功 |

## 完整性约束

- 不得删除或弱化验收条件以让实现通过。
- 不得使用跳过测试、空断言或测试专用后门。
- 外部依赖可以 mock，但不能用 mock 替代被验收的核心行为。
- 未实际运行的命令不得描述为“已验证”。
- 新增依赖前先确认现有依赖不能满足。
- 不提交真实素材、模型文件、缓存、日志或本地 QC 图片。

## 停止条件

出现以下情况时停止并请求用户决定：

- 源码复用或许可证权限不明确。
- 目标硬件无法运行候选转录后端。
- 需要写入或删除原始素材。
- 需要上传素材或转录稿。
- 发现当前需求与真实素材结构明显冲突。
- 需要改变 cut-list、隐私或 CLI 核心契约。
- 同一个验证连续失败三次且没有新证据。

## 最终评估

完成一个里程碑后，应由独立评估步骤重新执行：

- 实际 diff 审查。
- lint、类型检查和测试。
- 合成素材端到端流程。
- 原片指纹前后对比。
- 从源码目录外调用 CLI。
- 使用测试提示调用 Skill。
- 检查 Git 中没有本地素材、缓存和测试噪声。

---

# 22. 第一阶段完成定义

第一阶段不是“把所有旧脚本搬过来”，而是：

- 新仓库建立完成。
- PRD、架构决策和 CLI 契约落盘。
- 开发环境验证完成。
- CLI 可以安装。
- `init`、`doctor`、`status` 可用。
- JSON 输出和退出码稳定。
- 有自动化测试。
- 有可被 Codex 发现的 Skill 骨架。
- 后续 ingest、transcribe、sync、render 能在稳定基础上继续实现。

这组条件全部有新鲜验证证据后，才算 M1 完成。
