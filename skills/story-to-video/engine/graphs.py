"""ComfyUI API-format graphs: Z-Image-Turbo text-to-image and Wan2.2 TI2V-5B image-to-video (frames saved as PNGs)."""


def zimage_graph(prompt, seed, width, height, prefix, steps=8, shift=3.0, sampler="res_multistep",
                 scheduler="simple"):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "z_image_turbo_bf16.safetensors",
                                                     "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_4b_fp8_mixed.safetensors",
                                                     "type": "lumina2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": shift}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
        "7": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {"model": ["4", 0], "positive": ["5", 0], "negative": ["6", 0],
                                                   "latent_image": ["7", 0], "seed": seed, "steps": steps,
                                                   "cfg": 1.0, "sampler_name": sampler, "scheduler": scheduler,
                                                   "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": prefix}},
    }


def wan_i2v_graph(image_name, prompt, negative, seed, width, height, length, prefix, steps=20, cfg=5.0,
                  shift=8.0, fps=24, sampler="uni_pc", scheduler="simple", dtype="default", loras=()):
    """loras: [(file under models/loras, strength)] applied model-only before the sampling shift (e.g. a step-distill LoRA
    with steps=4, cfg=1). Without loras the graph is byte-identical to before."""
    g = _wan5b(image_name, prompt, negative, seed, width, height, length, prefix, steps, cfg, shift, sampler, scheduler, dtype)
    ref = ["1", 0]
    for i, (name, strength) in enumerate(loras):
        nid = str(20 + i)
        g[nid] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ref, "lora_name": name, "strength_model": strength}}
        ref = [nid, 0]
    g["4"]["inputs"]["model"] = ref
    return g


A14B_HIGH, A14B_LOW = "Wan2.2-I2V-A14B-HighNoise-Q4_K_S.gguf", "Wan2.2-I2V-A14B-LowNoise-Q4_K_S.gguf"
LIGHTNING_HIGH = "wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors"
LIGHTNING_LOW = "wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors"


def wan_a14b_i2v_graph(image_name, prompt, negative, seed, width, height, length, prefix, steps=4, split=2, cfg=1.0,
                       shift=5.0, sampler="euler", scheduler="simple", high=A14B_HIGH, low=A14B_LOW,
                       high_lora=LIGHTNING_HIGH, low_lora=LIGHTNING_LOW):
    """Wan2.2 I2V A14B (MoE: high-noise expert for steps [0, split), low-noise expert for [split, steps)), GGUF Q4 weights via
    ComfyUI-GGUF, lightx2v 4-step distill LoRAs (cfg 1 -> the negative prompt has no effect). 16 fps, Wan2.1 VAE."""
    g = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": high}},
        "2": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": low}},
        "7": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan",
                                                     "device": "default"}},
        "8": {"class_type": "VAELoader", "inputs": {"vae_name": "Wan2.1_VAE.safetensors"}},
        "9": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["7", 0], "text": prompt}},
        "10": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["7", 0], "text": negative}},
        "11": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "12": {"class_type": "WanImageToVideo", "inputs": {"positive": ["9", 0], "negative": ["10", 0], "vae": ["8", 0],
                                                           "width": width, "height": height, "length": length, "batch_size": 1,
                                                           "start_image": ["11", 0]}},
        "15": {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["14", 0], "vae": ["8", 0], "tile_size": 256, "overlap": 64,
                                                          "temporal_size": 4096, "temporal_overlap": 8}},
        "16": {"class_type": "SaveImage", "inputs": {"images": ["15", 0], "filename_prefix": prefix}},
    }
    hi, lo = ["1", 0], ["2", 0]
    if high_lora:
        g["3"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": hi, "lora_name": high_lora, "strength_model": 1.0}}
        hi = ["3", 0]
    if low_lora:
        g["4"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": lo, "lora_name": low_lora, "strength_model": 1.0}}
        lo = ["4", 0]
    g["5"] = {"class_type": "ModelSamplingSD3", "inputs": {"model": hi, "shift": shift}}
    g["6"] = {"class_type": "ModelSamplingSD3", "inputs": {"model": lo, "shift": shift}}
    common = {"noise_seed": seed, "steps": steps, "cfg": cfg, "sampler_name": sampler, "scheduler": scheduler,
              "positive": ["12", 0], "negative": ["12", 1]}
    g["13"] = {"class_type": "KSamplerAdvanced", "inputs": {**common, "model": ["5", 0], "add_noise": "enable", "latent_image": ["12", 2],
                                                            "start_at_step": 0, "end_at_step": split,
                                                            "return_with_leftover_noise": "enable"}}
    g["14"] = {"class_type": "KSamplerAdvanced", "inputs": {**common, "model": ["6", 0], "add_noise": "disable", "latent_image": ["13", 0],
                                                            "start_at_step": split, "end_at_step": 10000,
                                                            "return_with_leftover_noise": "disable"}}
    return g


def seedvr2_upscale_graph(video_name, prefix, resolution=1080, seed=42, batch_size=5, blocks_to_swap=32, tile=384):
    """SeedVR2 3B fp8 video upscaler (numz/ComfyUI-SeedVR2_VideoUpscaler). video_name: an mp4 in ComfyUI's input folder.
    resolution = target short side. batch_size must be 4n+1. 8 GB: block swap + tiled VAE, models offloaded to CPU."""
    return {
        "0": {"class_type": "LoadVideo", "inputs": {"file": video_name}},
        "1": {"class_type": "GetVideoComponents", "inputs": {"video": ["0", 0]}},
        "2": {"class_type": "SeedVR2LoadDiTModel", "inputs": {"model": "seedvr2_ema_3b_fp8_e4m3fn.safetensors", "device": "cuda:0",
                                                              "blocks_to_swap": blocks_to_swap, "offload_device": "cpu"}},
        "3": {"class_type": "SeedVR2LoadVAEModel", "inputs": {"model": "ema_vae_fp16.safetensors", "device": "cuda:0",
                                                              "encode_tiled": True, "encode_tile_size": tile, "encode_tile_overlap": 64,
                                                              "decode_tiled": True, "decode_tile_size": tile, "decode_tile_overlap": 64,
                                                              "offload_device": "cpu"}},
        "4": {"class_type": "SeedVR2VideoUpscaler", "inputs": {"image": ["1", 0], "dit": ["2", 0], "vae": ["3", 0], "seed": seed,
                                                               "resolution": resolution, "max_resolution": 0, "batch_size": batch_size,
                                                               "uniform_batch_size": False, "color_correction": "lab",
                                                               "offload_device": "cpu"}},
        "5": {"class_type": "SaveImage", "inputs": {"images": ["4", 0], "filename_prefix": prefix}},
    }


def _wan5b(image_name, prompt, negative, seed, width, height, length, prefix, steps, cfg, shift, sampler, scheduler, dtype):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_ti2v_5B_fp16.safetensors",
                                                     "weight_dtype": dtype}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                                                     "type": "wan", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
        "4": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": shift}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": negative}},
        "7": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "8": {"class_type": "Wan22ImageToVideoLatent", "inputs": {"vae": ["3", 0], "width": width, "height": height,
                                                                  "length": length, "batch_size": 1,
                                                                  "start_image": ["7", 0]}},
        "9": {"class_type": "KSampler", "inputs": {"model": ["4", 0], "positive": ["5", 0], "negative": ["6", 0],
                                                   "latent_image": ["8", 0], "seed": seed, "steps": steps,
                                                   "cfg": cfg, "sampler_name": sampler, "scheduler": scheduler,
                                                   "denoise": 1.0}},
        # Tiled from the start: a full 121-frame decode does not fit 8 GB. ComfyUI's own fallback (OOM -> tiled, 256 px tiles,
        # all frames at once) produced every accepted clip, but when the OOM turns into a slow VRAM spill instead of an error
        # the decode "hangs" (~1 in 3 attempts on 2026-10-03, 27 min lost each). Same tile/overlap as that fallback.
        "10": {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["9", 0], "vae": ["3", 0], "tile_size": 256, "overlap": 64,
                                                          "temporal_size": 4096, "temporal_overlap": 8}},
        # frames are saved as PNGs and assembled with ffmpeg by the caller (SaveVideo uses dynamic combo inputs)
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": prefix}},
    }
