# JustChangeWordInPhotoSkill

Change words in a photo or screenshot so the result is **indistinguishable from
the original printing**.

The hard part is not drawing text — it is making the drawn text *belong to
that photo*: same typeface, same weight, same ink darkness, same optical
softness, same paper texture. Pasting a clean vector word onto a photo is
immediately obvious to the eye.

This skill packages a repeatable method that reaches that result, plus every
failure that was hit along the way so you don't repeat them.

---

## What it does

| step | what it solves |
|---|---|
| **identify** | Finds the *actual* typeface of the original text by per-glyph shape matching (not by guessing PingFang) |
| **measure** | Measures the ink bbox, paper level, stroke width, ink core, blur sigma, per-character column groups |
| **erase** | Removes only the ink pixels — inpaint, so watermarks / seals / gradients stay exactly where they were |
| **render** | Composites the new text through the same optical model (camera PSF or browser anti-aliasing) |
| **verify** | Compares the result against a reference render (mask IoU) and checks background integrity |

Two reference case studies are documented end to end:

* a **photographed student card** (Kaiti SC Bold @160, fibrous ink bleed, blue paper, watermark band)
* a **UI screenshot** (Noto Sans CJK SC Regular @49, 1-px anti-aliasing ramp, flat white)

---

## Install

### As an agent skill

```bash
git clone https://github.com/che77a38/JustChangeWordInPhotoSkill.git \
    ~/.dsh/skills/photoswap-text
```

or symlink it into whichever skills directory your agent reads
(`~/.claude/skills/`, `~/.agents/skills/`, `~/.codex/skills/`, ...).

### As a standalone CLI

```bash
git clone https://github.com/che77a38/JustChangeWordInPhotoSkill.git
cd JustChangeWordInPhotoSkill
```

### Requirements

```bash
pip install pillow numpy
```

No `scipy`, no `cv2`, no GPU. Everything is numpy + Pillow.

### Fonts — fetched automatically

The skill does **not** bundle any font, because the right face depends on the
image. It works like this:

1. `fontid` compares the original glyphs against every CJK face it can find
   (the macOS/Windows system faces, plus any `.otf`/`.ttc` in the working
   directory or next to `SKILL.md`).
2. The families that are **not installed by default** — Noto Sans CJK and
   Source Han Sans, which most Chinese web pages use — are **downloaded
   automatically** into `scripts/fonts/` and take part in the comparison.
3. Only then is the winner reported.

That last step matters. If the image was made with Noto and Noto is not on
the machine, a matcher that only knows the system faces will confidently
answer *"PingFang SC Medium"* — a plausible-looking but wrong answer that no
amount of later tuning can fix.

Skip the download with `--no-download`, or point at your own copies with
`--font /path/to/YourFont.otf`.

The downloaded files are cached, so this costs one download, once.

---

## Quick start

```bash
cd scripts

# 1. What typeface is this really?
python3 photoswap.py fontid shot.png \
        --glyph "人:664,2083,709,2128" \
        --glyph "班:817,2083,862,2128" \
        --size 45,46,47,48,49,50,51,52

# 2. Where exactly is the ink?
python3 photoswap.py geometry shot.png --region 2178,1814,2812,1988 --thr 120

# 3. Replace the text
python3 photoswap.py edit shot.png \
        --region 2178,1814,2812,1988 \
        --text "人工智能" \
        --font /path/to/Kaiti.ttc --face 3 --size 160 \
        --align-x 2187 --valign top \
        --sigma 2.4 --edge 0.6 --gamma 1.25 --ink 10 12 18 \
        --dark-thresh 115 --ink-thresh 0.95 --min-run 2 --grow 7 \
        -o out.jpg

# 4. Look at it
python3 photoswap.py compare shot.png out.jpg --crop 2178,1814,2812,1988
```

### CLI reference

| subcommand | purpose |
|---|---|
| `fontid` | rank candidate typefaces for 2-3 given glyphs |
| `geometry` | ink bbox, paper level, per-character column groups → the erase box |
| `probe` | paper level, ink core, stroke widths, coverage, PSF sigma |
| `edit` | erase + render (+ optional `--extra` to re-lay the row's neighbours) |
| `compare` | side-by-side crop of original vs result |
| `verify` | background-integrity diff of original vs result |

---

## The three rules that decide acceptance

1. **Identify the face before you draw anything.** A wrong typeface cannot be
   fixed with a smaller sigma. Align candidates by their **ink bbox** — never
   force-resize them into a common box, or every candidate lands in a useless
   0.49–0.71 band and the real winner disappears.
2. **Erase only the characters, and only their ink.** A loose erase band
   swallows the background's own features (a watermark is dark enough to look
   like ink) and flattens them into a grey rectangle. Fill **per channel** —
   a luminance-only fill turns coloured paper neutral grey.
3. **Verify with pixels, not just statistics.** Render the expected string
   with the same font/size/box and compare **mask IoU** (must be ≈1.0) and
   `(edited & ~expected)` (must be 0). A fully green test suite once passed
   on an image where the new text was visibly superimposed on the old one —
   always *look* at a side-by-side crop.

Full details, all measured values and a 21-row failure catalogue:
[`SKILL.md`](SKILL.md) and [`references/parameters.md`](references/parameters.md).

---

## Intended use

This is a **fidelity / QA tool**: it is for authorised work on material you own
or are permitted to edit — test fixtures, localisation pipelines, mock-ups for
design review, privacy redaction, restoring damaged text in your own scans.

It is not intended to produce fraudulent identity documents, to defeat
verification systems, or to impersonate anyone.

---

## License

MIT — see [LICENSE](LICENSE).

The fonts are **not** bundled. The ones the skill fetches at runtime carry
their own licenses (Noto / Source Han: SIL OFL 1.1). The macOS system faces
it reads (PingFang, Kaiti, Hiragino) are proprietary and are only ever read
from the local machine, never redistributed.
