# 风格锁定与提示词写法

`engine/stylelock.py`：一部片用一个色盘、一组约束，逐字复用。预设可以选择带，没带就和不锁定完全一样。

- **字段**：
  - `palette_en / palette_zh`：这部片的色盘，`brief.py lock` 时可以用 `--palette-en` 覆盖预设默认。
  - `hard_constraints`：画面必须长什么样。
  - `banned_terms`：会把画面拉偏的词，lint 会在镜头提示词里查。
  - 人物卡里可以加 `signature_color / signature_pattern`，它们必须出现在 descriptor 里，lint 会查。
- **约束一律写正向**：写“平涂色块、均匀无投影的光、大面积留白”，不要写“不要阴影、不要渐变”。Z-Image-Turbo 的 guidance 只有 0–1，负向词基本不起作用：对比实验里，加和不加 “No shadows, no gradients...” 的两组，各项指标几乎一样。点名要避开的东西有时反而会被画出来（“不要葱”画出了葱）。否定词只放进 `wan_negative`（Wan 用 cfg 5 跑，负向词会生效；A14B 4 步是 cfg 1，也不生效）。
- **已经认可的提示词，不要为了消掉 lint 的否定警告整批改写**：“不露脸”这类属性否定，改不改写结果一样；改写反而会重掷已认可的关键帧，个别镜头还变差了。优先改**描述具体物体的否定**（“no people”“nothing on the floor”“不要葱”）。
- **衣服细节**：袖口撞色这类问题，写 “plain long sleeves of the same fabric down to the wrists” 比写否定句管用。样本很小，只当线索。
- **衬衫扣到顶**：普通领口不听 “buttoned up”，改成立领（band collar / mandarin collar）就稳定画成扣上的。年代感强的提示词里立领也会被画开，改成圆领上衣。
- **色盘的效果**（1 个场景 × 3 个种子，粗略指标）：锁定后平均饱和度 0.253 → 0.341，色盘色的像素占比约翻 3 倍。想让画面更“平”，光靠色盘不够，还要靠预设本身的 image_style。
- **借用别人的风格词**：先看对方的许可证。没有许可证 = 保留所有权利，只能借思路、用自己的话写。不要把真实工作室或作品的名字写进提示词、片名或宣传文案。
