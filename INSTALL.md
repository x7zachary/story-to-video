# 安装 / Installation

> 只在 **Windows 11 + NVIDIA RTX 8 GB 显存 + 32 GB 内存** 上完整测试过。Linux / macOS 未测试（`comfy.py` 用了 Windows 的进程管理方式）。
> Tested end to end only on **Windows 11, NVIDIA RTX with 8 GB VRAM, 32 GB RAM**. Linux / macOS are untested.

## 总览 / Overview
| 步骤 | 做什么 | 大概耗时 |
|---|---|---|
| 1 | 装 Python、Node.js、git、ffmpeg | 10–20 分钟 |
| 2 | 装 ComfyUI 和两个插件 | 20–40 分钟（主要是 PyTorch） |
| 3 | 给引擎建一个独立的 Python 环境 | 5 分钟 |
| 4 | 写配置、建工作区、装 Remotion | 5–10 分钟 |
| 5 | 放两个字体 | 2 分钟 |
| 6 | 下载模型（约 59 GB） | 国内直连 ModelScope 约 1 小时，视网速而定 |
| 7 | 体检、跑测试 | 2 分钟 |
| 8 | 安装 Claude Code 插件 | 1 分钟 |

下面的路径以 `D:/stv` 为例，换成你自己的。命令都在 PowerShell 或 Git Bash 里运行。

## 1. 准备 / Prerequisites
- Python 3.12+（测试用 3.14），Node.js 20+（测试用 24），git，ffmpeg（测试用 7.1；不需要 ffprobe）
- NVIDIA 显卡和驱动；PyTorch 按你的 CUDA 版本装（RTX 50 系用 cu128 测过）
- 磁盘：模型约 59 GB，另需工作区空间

## 2. ComfyUI 和两个插件 / ComfyUI and two custom nodes
```bash
git clone https://github.com/Comfy-Org/ComfyUI
```
按 ComfyUI 的 README 建 venv、装 PyTorch 和 requirements。然后在 `ComfyUI/custom_nodes/` 下：
```bash
git clone https://github.com/city96/ComfyUI-GGUF
```
```bash
git clone https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler
```
用 **ComfyUI 自己的 Python** 装插件依赖：
```bash
<ComfyUI>/venv/Scripts/python -m pip install -r setup/requirements-comfyui.txt
```
不要手动启动 ComfyUI；引擎会自己启动它（`--reserve-vram 1.5`）。如果你已经有一个在运行的 ComfyUI，在配置里设 `comfy_host`。

## 3. 引擎的 Python 环境 / Engine Python environment
引擎脚本用一个**独立的** Python 环境，不要和 ComfyUI 的混用。在本仓库目录里：
```bash
python -m venv D:/stv/.venv
```
```bash
D:/stv/.venv/Scripts/python -m pip install -r setup/requirements.txt
```
**之后所有 `python setup/...` 和 `python engine/...` 命令都用这个 Python**（`D:/stv/.venv/Scripts/python`），下文简写为 `python`。

## 4. 写配置、建工作区 / Configure the workspace
```bash
python setup/stv_setup.py init --workspace D:/stv --comfy-dir D:/stv/tools/ComfyUI --ffmpeg D:/tools/ffmpeg/bin/ffmpeg.exe --python D:/stv/.venv/Scripts/python.exe
```
- 配置写在 `~/.story-to-video/config.json`；每一项都可以用环境变量 `STV_<KEY>` 覆盖，见 `skills/story-to-video/engine/config.py`。
- 模型放在 ComfyUI 之外时，在配置里加 `"model_dirs": ["D:/models"]`，和 ComfyUI 的 `extra_model_paths.yaml` 指向同一处。
- `init` 会把 `remotion/` 模板复制到工作区，并生成胶片颗粒贴图。然后：
```bash
cd D:/stv/remotion && npm install
```

## 5. 字体 / Fonts
仓库**不带字体**。往 `<workspace>/remotion/public/fonts/` 放两个你有权使用的字体文件：
- `kai.ttf`：字幕、诗句，例如 [霞鹜文楷 LXGW WenKai](https://github.com/lxgw/LxgwWenKai)（SIL OFL 1.1）
- `title.ttf`：片名，例如 [Ma Shan Zheng 马善政毛笔楷书](https://fonts.google.com/specimen/Ma+Shan+Zheng)（SIL OFL 1.1）

## 6. 模型 / Models (~59 GB)
```bash
python setup/stv_setup.py models
```
```bash
python setup/stv_setup.py models --download
```
```bash
python setup/stv_setup.py models --verify
```
清单在 `setup/models.json`（仓库、文件、大小、sha256）。下载依次尝试 ModelScope → hf-mirror → huggingface.co，支持断点续传。各模型的许可证以模型卡为准，见 THIRD_PARTY.md。

## 7. 检查 / Check
```bash
python setup/stv_setup.py check
```
每一项前面都是 `OK`，最后一行是 `all good`，就说明装好了。显示 `MISS` 的行，箭头后面会写下一步怎么做。
全部 OK 后，在引擎目录里跑测试：
```bash
cd skills/story-to-video/engine && python -X utf8 test_lint.py && python -X utf8 test_chain.py && python -X utf8 test_music.py
```

## 8. 安装插件 / Install the Claude Code plugin
```bash
claude plugin marketplace add x7zachary/story-to-video
```
```bash
claude plugin install story-to-video@story-to-video
```
本地开发时也可以直接加载：`claude --plugin-dir ./story-to-video`。

## 已知坑 / Known pitfalls
- **Smart App Control（Windows）**：可能拦截新发布的二进制 wheel（WinError 4551）。改装发布较久的版本，**不要**关闭 SAC。可以先用 `setup/sac_probe.py <包目录>` 探测。
- **慢代理**：大文件都走 `hf_fetch.py`（可断点续传）；PyPI 可以换国内镜像。
- **8 GB 显存**：Wan 5B 必须用 fp8（引擎已默认）；fp16 会溢出到共享内存，一条约 79 分钟。
- **Remotion 的 Chrome Headless Shell** 下载卡住时：`python setup/get_headless_shell.py`（仅 Windows x64）。
