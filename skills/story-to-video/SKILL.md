---
name: story-to-video
description: 把一个故事或一首歌做成视频（Z-Image 出图 + Wan2.2 5B/A14B 动态镜头 + 代码叠加层 + edge-tts 配音 + Remotion 合成）。用户说"用这个故事做视频 / 给这首歌做 MV / 生成带配音的视频 / 升级镜头 / 补动态镜头"时使用。每个阶段先讨论再生成（D1 立项硬规则 → D2 文字分镜 → D3 定妆 → D4 L1 粗剪 → D5 动态方案 → D6 动态预览），manifest 驱动、可断点续跑。
---

# story-to-video

本地 AI 视频流水线：ComfyUI（Z-Image-Turbo 出图、Wan2.2 图生视频、SeedVR2 超分）+ edge-tts + Remotion。

- 脚本在本 skill 目录的 `engine/` 下，下文写的 `engine/xxx.py` 都相对于本 skill 目录。运行时用 config 里登记的 Python（`python -X utf8 engine/xxx.py ...`）。
- 路径都来自 `~/.story-to-video/config.json` 或环境变量 `STV_*`（见 `engine/config.py`）。项目在 `<projects>/<slug>/manifest.json`，manifest 是唯一事实来源。
- **第一次用**先跑插件根目录下的 `setup/stv_setup.py check`，缺什么按 INSTALL.md 补；环境装好后不要重装。
- 细节按需读：`references/motion.md`（动态分档、动作写法、审片清单、模型选择）、`references/style-lock.md`（风格锁定、提示词正向写法）、`references/hybrid-route.md`（代码动画 + AI 插图窗）、`references/lessons.md`（硬件实测、已查清 / 未验证、长任务和会话）。

## 路线选择（先于一切；选错路线会整套白做）
| 路线 | 适合 | 入口 |
|---|---|---|
| **A 叙事片**：出图 + Wan 动态 + 配音 + Remotion | 故事 / 传记 / 科普，旁白驱动，角色是一次性的 | 本文全部流程 |
| **B 歌曲 MV**：歌词对齐驱动 | 已有成品歌，镜头跟歌词和段落走 | `engine/lyrics.py`（转写 → 对齐 → 字幕）+ `engine/music.py`，其余同 A |
| **C 代码动画**：Remotion 矢量角色 + 少量背景板 | 吉祥物 / 品牌片，**角色每个镜头必须一模一样** | 在 Remotion 里写；共用 `music.py`、`lint.py`、`deliver.py` |
| **C+ 混合**：C 的主体 + 几个 AI 小片段做插图窗 | 讲规则 / 流程，文字必须零出错，又想要几个生活场景 | `references/hybrid-route.md` |

怎么选：①角色要不要处处一致？要 → C（Z-Image 没有参考图输入，做不到）。②声音：有成品歌 → B；要旁白 → A；音乐 + 画面文案 → C。③质感：写实 / 电影感 → A 或 B；平涂手绘 → A（`flat_gouache`）或 C。拿不准就问用户，不要默认走 A。

## 流程
```
D1 立项+硬规则 → D2 文字分镜表 → D3 定妆 → lint.py → L1 出图+粗剪 → D4 L1 签字
  → D5 动态方案 → L2a 动态片段 + 审片 → pipeline.py preview → D6 预览签字 → L2b 定稿（超分、渲染）→ deliver.py
```
每一级都可以停下来交付。D1–D6 是讨论节点：先给方案，等用户回复再花 GPU。

## 讨论节点（每个项目都走）
原则：**能用文字定的事，在花 GPU 之前定下来**。每个节点准备好方案（选项 + 推荐默认 + 下一步要花多少时间），用户回复后再动手，决定写进项目的 `notes/decisions.md`。用户不在（无人值守）时按推荐默认走，并在 decisions.md 里标“自动决定，待确认”。一个节点一条消息，问题不超过 4 个，用 AskUserQuestion 或表格。

| 节点 | 时机 | 准备什么 | 用户定什么 | 不定的代价（一个真实 MV 项目里的返工） |
|---|---|---|---|---|
| D1 立项 | 拿到素材后 | 路线、画幅、时长、画风样图、**硬规则清单草稿** | 选项；补全硬规则 | 规则分 3 次在出图后才提出（服装统一、发型、扣子、食物），约 20 张关键帧重出 |
| D2 文字分镜 | 出图前，不花 GPU | `engine/board.py` 分镜表：镜号 / 时间 / 歌词或旁白 / 画面 / 人物 / 动态档与模型 / 动作 / lint 提醒 | 故事逻辑、每镜动不动、怎么动 | 不花钱就能改的东西，拖到跑完动态后才改 |
| D3 定妆 | 批量出图前 | 每个反复出现的人物 2–3 张候选标准像（按规则用背影 / 侧面 / 正面）+ 1 张代表场景 | 选定后锁定人物描述串 | 人物外观在几十张图里漂移，衣色、发型改了 3 轮 |
| D4 L1 签字 | 静帧粗剪后 | L1 成片 + 镜头总览图 | 节奏、画面、字幕 | — |
| D5 动态方案 | 开 Wan 前 | 每镜的动态档、自动选出的模型、`pipeline.py estimate` 的 GPU 时间、高风险镜头 | 哪些镜头值得做 AI 动作 | “全部都动起来”→ 59/60 交给 Wan，19.4 小时 GPU，很多画面不合逻辑 |
| D6 动态预览 | L2a 跑完 | `pipeline.py preview` 低清整片（镜号、状态、速度、歌词烧在画面上）+ 审片意见 | 逐镜 OK / 改法 | 交付后才发现不合逻辑 |

**D1 硬规则清单**（一次问全）：
- 每个反复出现的人物：年龄、发型（具体到“满头白发寸头、不秃顶”这种程度）、服装（颜色、款式、领口、扣子）、绝对不能出现的（例如“全片不露脸”）。
- 内容禁忌：宗教或场所元素、食物（荤素、葱蒜）、品牌、年代错误的物品。
- 统一要求：衣服扣法、配色、季节、时代、地点。
- 对白类歌词 / 台词：对口型，还是意境化。

## Stage 0 导演简报
`engine/brief.py init <slug> <story.txt> --title T` → `engine/brief.py samples <slug> --scene "<代表性场景>"`（每种画风出 1 张样图，约 2 分钟一张）。
- 交互模式：用 AskUserQuestion 问平台 / 画幅、目标时长、画风（附样图）、旁白语气；钩子给 3 个候选让用户选。
- 自动模式：历史 / 传记 / 悬疑 → `cinematic_realistic`；诗词 / 山水 → `ink_wash`；儿童 / 科普 → `storybook`；神话 / 寓言要平涂手绘感 → `flat_gouache`。默认 16:9，提到抖音 / 视频号 / 竖屏 → 9:16。理由写进 brief.md，保留样图供事后改。
- 钩子（前 3–6 秒）：写 3 个候选（冷开场引语 / 悬念问句 / 强视觉），`brief.py hook` 打分选最优。不要用“静默风景 + 字卡”开场。
- `engine/brief.py lock <slug> --preset ID --aspect 16:9 --mode auto|interactive [--palette-en ...]` 写 style.json 和 manifest 骨架。风格锁定的细节见 `references/style-lock.md`。

## Stage 1 分镜 + 配音 + 时间轴
1. 人物卡：`{"HERO": {"descriptor": "固定描述串（年龄 / 面相 / 服装颜色）"}}`，镜头提示词里用 `{HERO}` 引用，描述串逐字复用。只能动镜头和环境的人物加 `"hold_still": true`。
2. 写 manifest 的 `segments`（旁白 / 对白：speaker、text、shots）、`voices`、`tts_replace`、`shots`。
3. 路线 A：`engine/audio.py <slug> tts` → `engine/timeline.py <slug>`（算真实时长、字幕、镜头区间，并校验镜头长度）→ `audio.py <slug> mix`。配音质检：`asr_check.py` 后 `pinyin_diff.py`（拼音级比对，只能抓漏读或读错音节，不能证明声调）。
4. 路线 B：manifest 写 `"song"`，歌词放 `lyrics.txt` → `engine/lyrics.py <slug> transcribe` → `align` → `subtitles`；节拍和段落候选用 `engine/music.py <歌>`。
5. **D2**：`engine/board.py <slug> --out notes/storyboard.md`。镜头上可写 `desc_zh`（画面一句话）、`motion_zh`（动作一句话），表里优先显示。

**分镜规则**：
- 静帧镜头 4–8 秒。动态镜头不超过约 5.5 秒，更长就拆成“全景 + 局部特写”，第二个镜头写 `reuse_of: <id>, zoom: 1.6, focus: [x, y]`（同一关键帧换个裁切，不额外出图）。
- 对话用正反打，两人各一张关键帧交替用。
- 每个镜头必填 `type, motion_class, importance(1-5), hero`；可选 `motion_tier`（`camera / overlay / ai_env / ai_action`）、`move`（`in / out / left / right / up / still`）、`flashback`、`overlay`、`wan_model`。
- 人物镜头多用侧面、背影、远景、剪影，少用正脸特写（特写最容易身份漂移）。
- 动态分档和动作写法：**先读 `references/motion.md`**。

## L1 粗剪（签字点）
先 `engine/lint.py <slug>`：0 个 ERROR 才出图；WARN 逐条看，`[motion]` 类提醒对应 motion.md 的规则。
`engine/stills.py <slug> L1 --shots ...`（1344×768，每镜 1 张，数值预筛）→ 逐镜看图，替换坏图（畸形手、乱码文字、现代物品、串角色）→ `engine/pipeline.py render <slug> L1`。
**这里审节奏、钩子、分镜、字幕**，之后每一步都贵。没过 D4 不要开 Wan。
注意：`stills.py` 不加 `--shots` 会把每个镜头的候选 c0 重新拷成关键帧，覆盖人工改选的结果。

## L2 动态
1. **D5**：`pipeline.py queue <slug>` 看排序，`pipeline.py estimate <slug> --budget-min 240` 看每镜的模型、原因和期望 GPU 分钟（A14B 的超分时间单独列）。预算不够先砍低分镜头。
2. `pipeline.py upgrade <slug> --budget-min 240 [--unattended]`，**独立进程启动**（见 lessons.md）。模型按镜头自动选：人物 / 手 / 物体 / 有表演 → A14B，纯环境 → 5B，5B 失败过的镜头自动升级到 A14B；`--model`、镜头上的 `wan_model`、manifest 顶层的 `wan_model` 可以覆盖。
   - 看门狗：步速停滞 / 解码挂起 / 服务无响应 → 中断并重启 ComfyUI。
   - 数值 QC：太静止 → 失败；突变 → 自动截帧。
   - 重试链：原提示词 → 保守运动提示词 + 换种子 → 降档；仍失败就回落静帧。
   - 尾帧接续（可选）：`"continue_from": <id>` 让一个连续动作超过 5 秒，链条别超过 2 环。
3. **审片**：按 motion.md 的审片清单看 `clips/raw/shot_XX_review.jpg`（12 帧），用 `pipeline.py review <slug> <shot> ok|reject [--keep N] --note "第几项：……"` 登记。`--unattended` 跑出来的片段是 `ok_unreviewed`，成片报告必须注明“未人工审片”。
4. **D6**：`pipeline.py preview <slug>` 约 20 秒出低清整片，交给用户按镜号提意见。改法从“简化动作 / 降到 camera 或 overlay / 换种子 / 换 A14B”里选。
5. 定稿：`pipeline.py upscale <slug>`（SeedVR2 把低于 1080p 的片段，即 A14B 的，放大到 1080p）→ `pipeline.py render <slug> L2`。

## 交付前检查
`engine/deliver.py <成片.mp4> --out <交付.mp4> --sheet <总览.jpg> --frames 24 --expect-duration <秒> --expect-size 1920x1080`：
- 转成限幅 yuv420p + faststart；
- 量响度和峰值（目标约 -16 LUFS ±3，峰值不超过 -1 dBFS）；
- 抽帧拼总览，写 report.json；
- 有 ERROR 时退出码为 1，不覆盖已有文件。

它不检查字幕溢出（字幕长度由 lint 按源数据查）。自己逐张看总览图。成片报告写清：每个镜头是动态还是静帧、哪些未审片，以及配音读音只做了 ASR 拼音比对，仍建议人耳过一遍。

## 人物一致性
- 一次性视频：人物卡（固定描述串 + D3 选定的标准像）就够了。
- 系列 / 固定主角需要处处一致：走路线 C。Z-Image-Turbo 没有参考图输入，不用换脸方案（InsightFace 模型非商用授权）。
