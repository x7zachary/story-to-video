# 实测数据、已查清 / 未验证、长任务与会话

## 实测耗时（Windows 11，RTX 5060 Laptop 8 GB，32 GB 内存）
| 步骤 | 设置 | 耗时 |
|---|---|---|
| Z-Image-Turbo 出图 | 1344×768，8 步 | 约 2 分钟 / 张（含加载模型） |
| Wan2.2 TI2V-5B | fp8，1280×704，121 帧，20 步 | 约 13.8 分钟 / 条（fp16 会溢出显存，约 79 分钟） |
| Wan2.2 TI2V-5B 快速档 | 960×544，81 帧，16 步 | 约 3.4 分钟 / 条 |
| Wan2.2 I2V A14B | GGUF Q4_K_S + lightx2v 4 步，848×480，81 帧 | 约 5 分钟 / 条 |
| SeedVR2 3B fp8 | 480p → 1080p，81 帧，batch 5，384 px 分块 | 约 8 分钟 / 条 |

- 8 GB 显存：Wan 5B 必须用 fp8 加 ComfyUI `--reserve-vram 1.5`。121 帧 1280×704 的整段 VAE 解码装不进 8 GB，所以 graph 一开始就用分块解码（`VAEDecodeTiled`）。SeedVR2 用 batch 21 会 OOM。
- Remotion 渲染时，Wan 的步速会变慢（约 34 秒变 48 秒一步），属正常。

## 长任务与会话
- 长任务（`stills.py` / `pipeline.py upgrade` / `upscale`）放独立进程跑：Windows 上用 PowerShell `Start-Process`，其他系统用 `nohup`。Agent 的后台任务有时间上限，会被杀掉。进度用 `pipeline.py status <slug>` 查。
- `pipeline.py review` 要等 `upgrade` 进程结束后再登记，否则会被 upgrade 保存的 manifest 覆盖。
- 一个阶段一个会话（立项 + 分镜 / 出图 / 动态 / 渲染交付）。状态全在 manifest 和 `notes/` 里，换会话前写 `notes/handoff.md`。一个会话连着跑一周、看上百张图，后来每次请求要等十几分钟，还会超时失败。
- 审片图看小图、分批看，结论用 `pipeline.py review` 写进 manifest，不要在对话里堆图。
- `test_watchdog.py` 会挂起正在运行的 ComfyUI 进程，不要在生产任务进行时跑。

## Windows 和网络
- Smart App Control 开启时，新发布的二进制 wheel 可能被拦（WinError 4551）。换一个发布较久的版本；**不要**为此关闭 SAC 或其他安全设置。装新依赖前可以先用 `setup/sac_probe.py` 探测。
- faster-whisper 只在解码文件时需要 PyAV；本项目用 ffmpeg 解码，所以 PyAV 被拦也不影响（代码里用了一个空模块占位）。
- 下载大模型：`hf_fetch.py` 依次尝试 ModelScope（国内直连快）→ hf-mirror → huggingface.co，支持断点续传。下完用 `stv_setup.py models --verify` 核对 sha256。

## 已查清（来自 README 和模型卡，并在本机实测过）
- Wan2.2 TI2V-5B 没有官方 Lightning 版，但有第三方的 5B 加速 LoRA（FastWan、Turbo）：能提速，不能修逻辑。
- A14B + lightx2v 4 步 LoRA 用 GGUF Q4 能在 8 GB 显存 + 32 GB 内存上跑。
- Qwen-Image-Edit-2511 在 8 GB 上只能跑 Q2/Q3，质量受损，不适合用来做参考图一致性。
- Z-Image-Turbo：guidance 0、8 步，负向词无效。Z-Image Base 支持负向词，但慢很多（未实测）。

## 尚未验证（不要当作已有能力）
- 补帧：RIFE 补帧（现在 16→30 fps 用的是 ffmpeg minterpolate，大动作可能扭曲）。
- 音效模型：MMAudio、HunyuanVideo-Foley。
- 参考图：FLUX Kontext 重出特写。
- 9:16 竖屏流程。
- 画风稳定性：`ink_wash`、`storybook` 预设下 Wan 能不能保持画风。`flat_gouache` 预设下大动作（站起、转身）到后半段会碎，小动作（呼吸、眨眼、蒸汽、星光）比较稳。
