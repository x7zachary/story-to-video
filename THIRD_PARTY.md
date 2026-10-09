# Third-party software and models / 第三方软件与模型

This repository contains only original code and docs, licensed under Apache-2.0 (see LICENSE).
**Nothing below is bundled.** Users install each component themselves and must follow its own license.
本仓库只包含原创代码和文档（Apache-2.0）。下列组件**都不随仓库分发**，由用户自行安装，并须遵守各自的许可证。

## Software / 软件
| Component | License | Notes |
|---|---|---|
| [ComfyUI](https://github.com/Comfy-Org/ComfyUI) | GPL-3.0 | Used as a separate local server over its HTTP API; not linked or redistributed. |
| [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) | Apache-2.0 | Custom node, installed by the user. |
| [ComfyUI-SeedVR2_VideoUpscaler](https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler) | Apache-2.0 | Custom node, installed by the user. |
| [Remotion](https://www.remotion.dev) | **Remotion License (not open source)** | Free for individuals, for-profit organisations with up to 3 employees, and non-profits. **Larger companies need a paid company license.** See remotion.dev/license. |
| [edge-tts](https://github.com/rany2/edge-tts) | LGPL-3.0 | Calls Microsoft Edge's online read-aloud voices. This is not an official Microsoft API; check its terms before commercial use. |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | |
| [pypinyin](https://github.com/mozillazg/python-pinyin) | MIT | |
| opencc-python-reimplemented | Apache-2.0 | |
| ffmpeg | LGPL / GPL (depends on build) | Called as an external program. |

## Models / 模型（downloaded by `setup/stv_setup.py models`, see `setup/models.json`）
| Model | Used for | License (check the model card) |
|---|---|---|
| Z-Image-Turbo (Comfy-Org repack) | stills | see the Z-Image model card |
| Wan2.2 TI2V-5B, Wan2.2 I2V A14B (GGUF by QuantStack), Wan VAEs, umT5 encoder | image-to-video | Wan2.2: Apache-2.0 |
| lightx2v Wan2.2 4-step distill LoRAs | A14B speed-up | see the lightx2v model card |
| SeedVR2 3B (numz repack) | video upscaling | Apache-2.0 |

Model outputs and your use of them are governed by those licenses and by local law. Mark AI-generated material as such where required.
模型生成的内容及其使用，受上述许可证和当地法律约束；按要求标注 AI 生成。

## Fonts / 字体
No fonts are included. The templates expect `kai.ttf` and `title.ttf` supplied by the user (for example LXGW WenKai and Ma Shan Zheng, both SIL OFL 1.1).
仓库不含字体，由用户自行提供 `kai.ttf` 和 `title.ttf`。

## Ideas / 思路来源
Some checks were inspired by public projects (ideas only, no code copied): the markdown cross-reference checker in zenstory-ai/drama-skills (lint) and the post-render self-review in OpenMontage (deliver).
