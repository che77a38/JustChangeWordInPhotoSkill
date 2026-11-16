# JustChangeWordInPhotoSkill

在照片或截图里改字，改到**与原始印刷效果无法分辨**。

难的从来不是"把字画上去"，而是让画上去的字**属于那张照片**：同一款字库、同样的字重、同样的墨色深浅、同样的光学柔和度、同一张纸的纹理。把一个干净的矢量字直接贴到照片上，眼睛一眼就能看出来。

这个 skill 把达成这个效果的方法固化成了可重复的流程，并把开发过程中踩过的每一个坑都记了下来 —— 让你不必重走一遍。

---

## 它解决什么

| 步骤 | 解决的问题 |
|---|---|
| **识别字体** | 逐字形形状匹配，找出原图**真正**用的字库（而不是默认猜 PingFang） |
| **测量** | 量出墨迹外框、纸面亮度、笔画宽度、墨核颜色、模糊 sigma、逐字列分组 |
| **擦除** | 只抹掉墨迹像素 —— 用 inpaint 扩散填充，水印／印章／渐变原地不动 |
| **渲染** | 用同一套光学模型（相机 PSF 或浏览器抗锯齿）把新字合成上去 |
| **验收** | 与参考渲染比对掩膜 IoU，并检查背景完整性 |

附带两个完整的实测案例：

* **实拍学生证**（Kaiti SC Bold @160、纤维状渗墨、蓝色纸张、水印带）
* **UI 截图**（Noto Sans CJK SC Regular @49、1 像素抗锯齿过渡、纯白底）

---

## 安装

### 作为 agent skill

```bash
git clone https://github.com/che77a38/JustChangeWordInPhotoSkill.git \
    ~/.dsh/skills/photoswap-text
```

也可以软链到你所用 agent 的 skills 目录
（`~/.claude/skills/`、`~/.agents/skills/`、`~/.codex/skills/` 等）。

### 作为独立 CLI 使用

```bash
git clone https://github.com/che77a38/JustChangeWordInPhotoSkill.git
cd JustChangeWordInPhotoSkill
```

### 依赖

```bash
pip install pillow numpy
```

不需要 `scipy`、不需要 `cv2`、不需要 GPU。全部用 numpy + Pillow 实现。

### 字体 —— 自动获取，不随仓库分发

仓库里**不含任何字体文件**，因为用哪款字体取决于图片本身。工作方式如下：

1. `fontid` 把原图里的字，与它能找到的每一个中文字库逐一比对
   （macOS／Windows 系统字体，加上工作目录或 `SKILL.md` 旁边的任何 `.otf`／`.ttc`）。
2. 对于**默认没有安装**的字体族 —— Noto Sans CJK 和 Source Han Sans，
   绝大多数中文网页用的就是它们 —— 会**自动下载**到 `scripts/fonts/`，
   并一起参与比对。
3. 比对完成后，才给出结论。

第三步是关键。如果图片是用 Noto 做的、而本机没有 Noto，那么一个只认识系统字体的匹配器会**自信地**回答「PingFang SC Medium」—— 一个看着很像、实则错误的答案，而这种错误后面无论怎么调参数都救不回来。

下载的文件会缓存，所以只需要下载一次。

用 `--no-download` 可以关掉自动下载；用 `--font /path/to/YourFont.otf` 可以指定你自己的字体文件。

---

## 快速上手

```bash
cd scripts

# 1. 这到底是什么字体？
python3 photoswap.py fontid shot.png \
        --glyph "人:664,2083,709,2128" \
        --glyph "班:817,2083,862,2128" \
        --size 45,46,47,48,49,50,51,52

# 2. 墨迹到底在哪？
python3 photoswap.py geometry shot.png --region 2178,1814,2812,1988 --thr 120

# 3. 改字
python3 photoswap.py edit shot.png \
        --region 2178,1814,2812,1988 \
        --text "人工智能" \
        --font /path/to/Kaiti.ttc --face 3 --size 160 \
        --align-x 2187 --valign top \
        --sigma 2.4 --edge 0.6 --gamma 1.25 --ink 10 12 18 \
        --dark-thresh 115 --ink-thresh 0.95 --min-run 2 --grow 7 \
        -o out.jpg

# 4. 用眼睛看
python3 photoswap.py compare shot.png out.jpg --crop 2178,1814,2812,1988
```

### CLI 命令一览

| 子命令 | 用途 |
|---|---|
| `fontid` | 给定 2-3 个字形，对候选字库排名 |
| `geometry` | 墨迹外框、纸面亮度、逐字列分组 → 据此确定擦除框 |
| `probe` | 纸面亮度、墨核颜色、笔画宽度、覆盖率、PSF sigma |
| `edit` | 擦除 + 渲染（可用 `--extra` 重排同一行的相邻元素） |
| `compare` | 生成原图与结果的并排裁切图 |
| `verify` | 原图与结果的背景完整性 diff |

---

## 决定成败的三条铁律

1. **先认字体，再动笔画。** 字库认错了，不可能靠调小 sigma 救回来。
   候选字形必须按各自的**墨框**对齐 —— 绝不要强行缩放到同一个框里，
   否则所有候选都会挤进 0.49–0.71 这个无意义区间，真正的赢家直接消失。
2. **只擦要替换的那几个字，而且只擦它们的墨。** 擦除框一松，就会把背景
   自身的特征一起吞掉（水印的暗度足以被当成文字），最后留下一块死灰色矩形。
   填充必须**逐通道**做 —— 只填亮度通道会把彩色纸变成中性灰。
3. **用像素验收，不能只看统计数字。** 用同样的字体／字号／目标框渲染一次
   期望字符串，然后比对**掩膜 IoU**（应 ≈ 1.0）和 `(edited & ~expected)`
   （应为 0）。曾经有一次全绿的测试套件通过了一张**新字明显压在旧字上**的图 ——
   所以一定要**看**一眼并排裁切图。

全部细节、实测参数表和 21 行故障诊断表见
[`SKILL.md`](SKILL.md) 与 [`references/parameters.md`](references/parameters.md)。

---

## 使用边界

这是一个**保真度／QA 工具**：用于你拥有或有权编辑的素材 —— 测试夹具、
本地化流程、设计评审用的效果图、隐私打码、修复自己扫描件的破损文字。

它不用于伪造身份证件、不用于绕过验证系统、不用于冒充他人。

---

## 许可

MIT —— 见 [LICENSE](LICENSE)。

字体**不随仓库分发**。skill 运行时自动获取的字体各自遵循其许可
（Noto / Source Han 为 SIL OFL 1.1）；它读取的 macOS 系统字体
（PingFang、Kaiti、Hiragino）属专有字体，只从本机读取，绝不分发。
