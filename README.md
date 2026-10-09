# story-to-video

**一个 Claude Code 插件：你给 Claude 一个故事或一首歌，它在你自己的电脑上一步步做成视频，每一步做之前先和你商量。**
**A Claude Code plugin: give Claude a story or a song, and it turns it into a video on your own computer, checking with you before each step.**

> 早期版本 / Early version：只在一台 Windows 11 + RTX 8 GB 显卡的电脑上完整跑通过。欢迎提 issue。

[中文](#中文) · [English](#english)

---

## 中文

### 适合谁
- 想用**本地开源模型**做短视频：故事 / 传记 / 科普配音短片、给自己的歌做 MV、品牌或产品宣传片。
- 有一块 **NVIDIA 显卡（8 GB 显存起）**、**32 GB 内存**、约 **70 GB 磁盘空间**，愿意花一两个小时装环境。
- 已经在用 [Claude Code](https://code.claude.com)。

不适合：没有 NVIDIA 显卡的电脑（包括 Mac）；需要对口型的数字人；想一句话直接出成片、不想参与中间决定。

### 快速开始
1. **装环境**：按 [INSTALL.md](INSTALL.md) 装 ComfyUI、下载模型、配置工作区，最后运行 `python setup/stv_setup.py check`，全部显示 OK 就算装好了。
2. **装插件**：在终端运行
   ```bash
   claude plugin marketplace add x7zachary/story-to-video
   ```
   ```bash
   claude plugin install story-to-video@story-to-video
   ```
3. **开始做**：打开 Claude Code，直接说需求，比如：
   > 用这个故事做一个 1 分钟的视频，竖屏，水墨风：（贴上故事）
   > 给这首歌做 MV，歌曲在 D:/music/song.mp3，歌词如下：……

### 做一个视频是什么样的过程
Claude 会按 6 个**讨论点**推进。每到一个讨论点就停下来给你方案和推荐，等你回复再继续，避免做完才发现方向不对：

| 步骤 | Claude 做什么 | 你要做什么 | 大概耗时（8 GB 显卡） |
|---|---|---|---|
| D1 立项 | 问画幅、时长、画风，出几张风格样图；列一份“硬规则”清单（人物长相服装、不能出现的东西） | 选风格，补全规则 | 每张样图约 2 分钟 |
| D2 文字分镜 | 写分镜表：每个镜头的画面、旁白或歌词、动不动、怎么动 | 看表、改表（还没花 GPU） | 几分钟 |
| D3 定妆 | 给主要人物出几张候选标准像 | 选一张 | 每张约 2 分钟 |
| D4 静帧粗剪 | 每个镜头出一张图，配上配音或歌曲、字幕，合成静帧版成片 | 看节奏和画面 | 每个镜头约 2 分钟 |
| D5 动态方案 | 决定哪些镜头只做运镜、哪些加代码特效（飘雪、灰尘、萤火……）、哪些用 AI 动起来，并估算时间 | 确认 | — |
| D6 动态预览 | 跑 AI 动态，拼一条标好镜号的低清预览片 | 按镜号说哪里不对 | AI 镜头每条 5–14 分钟 |
| 定稿 | 修改、放大到 1080p、合成、交付检查 | 验收 | 每个 AI 镜头再加约 8 分钟 |

一个 1 分钟、15 个镜头的片子，静帧版一小时左右能出来；如果一半镜头做 AI 动态，GPU 还要跑几个小时，可以挂着过夜。

### 会生成什么
每个视频是工作区里的一个项目文件夹：
```
projects/<名字>/
  manifest.json        所有镜头、提示词、状态（唯一的事实来源，可断点续跑）
  notes/               decisions.md（你定下的规则）、storyboard.md（分镜表）
  images/  clips/      关键帧、AI 动态片段和审片拼图
  audio/               配音或歌曲、对齐好的字幕
  output/              成片、预览片、交付报告
```

### 它和"一句话出视频"的区别
- **先讨论后生成**：能用文字定的事，都在花 GPU 之前定好。
- **不是每个镜头都交给 AI**：一个镜头怎么动分四档，从低到高依次是只动镜头、代码画特效（不花 GPU，也不会画错）、AI 只动环境、AI 动人物。
- **按镜头自动选模型**：人物和物体用 Wan2.2 A14B（更稳），纯风景用 Wan2.2 5B。5B 失败过的镜头会自动升级到 A14B。
- **生成前检查**：一个镜头里动作写太多、东西凭空进画、需要拉慢放这类会让画面不合逻辑的问题，生成前就会提醒。
- **审片有清单**：东西有没有凭空出现或消失、人数和脸前后是否一致、动作合不合理，都会逐条检查。

### 常见问题
- **能商用吗？** 本仓库的代码是 Apache-2.0。但 **Remotion 对 3 人以上的公司收费**；edge-tts 用的是微软的在线语音，不是官方接口；模型各有许可证。详见 [THIRD_PARTY.md](THIRD_PARTY.md)。
- **Mac / Linux 能用吗？** 目前没有测试过。Mac 没有 NVIDIA 显卡，跑不动这些视频模型。
- **只有 6 GB 显存？** 没测过。A14B 用的是 Q4 量化，加上内存卸载，也许能跑，但会更慢。
- **字体呢？** 仓库不带字体（版权原因）。按 INSTALL.md 放两个开源字体。

### 仓库里有什么
```
.claude-plugin/          插件和插件市场的清单
skills/story-to-video/   SKILL.md（给 Claude 看的流程）、references/（细节）、engine/（Python 脚本和测试）
remotion/                视频合成模板（字幕、片头、代码特效叠加层）
setup/                   安装和检查脚本、依赖清单、模型清单（带 sha256）
examples/                示例项目（《桃花源记》）
```

---

## English

### Who it is for
- You want to make short videos with **local open models**: narrated stories / biographies / explainers, an MV for your own song, a brand or product promo.
- You have an **NVIDIA GPU with 8 GB+ VRAM**, **32 GB RAM**, about **70 GB of disk**, and an hour or two for setup.
- You already use [Claude Code](https://code.claude.com).

Not for: machines without an NVIDIA GPU (including Macs), lip-synced talking heads, or one-click videos with no decisions on your side.

### Quick start
1. **Set up**: follow [INSTALL.md](INSTALL.md) (ComfyUI, models, workspace), then run `python setup/stv_setup.py check` until everything is OK.
2. **Install the plugin**:
   ```bash
   claude plugin marketplace add x7zachary/story-to-video
   ```
   ```bash
   claude plugin install story-to-video@story-to-video
   ```
3. **Ask Claude**, for example: "Make a 1-minute vertical video from this story in ink-wash style: …" or "Make an MV for this song (path, lyrics …)".

### What a run looks like
Claude works through six **checkpoints**. At each one it stops with a proposal and waits for your answer:
- **D1 brief**: format, length, style samples, and a list of hard rules (how characters look, what must never appear).
- **D2 text storyboard**: no GPU used yet.
- **D3 character looks**.
- **D4 still cut**: one image per shot, with voice or song and subtitles.
- **D5 motion plan**: which shots get a camera move, a code-drawn effect, or AI motion, with a time estimate.
- **D6 motion preview**: a labelled low-res preview to give feedback on by shot number.

After that it finalises: fixes, 1080p upscaling, render and delivery checks.

On an 8 GB GPU, timings are roughly:
- a still: about 2 min;
- an AI motion clip: 5–14 min;
- 1080p upscale: about 8 min per AI clip.

For a 1-minute, 15-shot film, the still cut is ready in about an hour. AI motion for half the shots takes a few more GPU hours, which can run overnight.

### Output
Each video is a project folder with:
- `manifest.json`: the single source of truth, so a run can resume where it stopped;
- `notes/`: your decisions and the storyboard;
- `images/`, `clips/`, `audio/`;
- `output/`: final film, preview, delivery report.

### License
Code and docs: Apache-2.0. Dependencies and models are **not bundled** and carry their own licenses (see [THIRD_PARTY.md](THIRD_PARTY.md)):
- **Remotion is not open source**: companies with more than 3 employees need a paid license.
- edge-tts uses Microsoft's online voices and is not an official API.
