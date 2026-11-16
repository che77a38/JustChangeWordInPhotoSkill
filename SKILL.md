---
name: photoswap-text
description: Replace or change text in a photo or screenshot (ID card, student card, certificate, form, receipt, UI screenshot) so the new text is indistinguishable from the original print - identifying the original typeface, matching size, ink darkness, stroke weight, blur and paper texture. Use when the user asks to P-edit, change, replace, swap or forge text in an image, edit a document/card/screenshot, or wants a text swap that must look authentic.
---

# photoswap-text

Change words in a photo so the result is indistinguishable from the original
printing. The hard part is not drawing text - it is making the drawn text
*belong to that photo*: same face, same weight, same ink, same optical
softness, same paper.

## Workflow: identify → measure → erase → render → verify

**Do not start by editing.** The question that decides whether a swap looks
native is *"which typeface is this?"* — answer it BEFORE any rendering, because
every later parameter (size, stroke width, ink darkness) depends on it.

```bash
cd ~/.dsh/skills/photoswap-text/scripts

# 1. IDENTIFY the typeface (§1) — cut 2-3 glyphs, rank all candidate faces
python3 photoswap.py fontid shot.png \
        --glyph "人:664,2083,709,2128" --glyph "2:555,2083,578,2128" \
        --size 45,46,47,48,49,50,51,52 --top 12

# 2. MEASURE the original ink (bbox, paper level, stroke width, ink core)
python3 photoswap.py probe shot.png --region 555,2078,861,2129 --sample "2026人资03班"

# 3. ERASE only the ink of exactly the characters being replaced (§2)
#    (inpaint, tight box, per-channel fill)

# 4. RENDER the new text at the identified face/size (§3-§5)
python3 photoswap.py edit shot.png --region 555,2078,861,2129 \
        --text "2026人工智能03班" --font ./NotoSansCJKsc-Regular.otf --face 0 \
        --size 49 --align-x 555 --valign top \
        --sigma 0.15 --edge 0.5 --grain off --ink 51 51 51 -o out.png

# 5. VERIFY — numbers AND pixels, every time
python3 photoswap.py compare shot.png out.png --crop 555,2078,861,2129
python3 photoswap.py verify shot.png out.png --region 555,2078,861,2129
```

`compare` and `verify` are not optional. Render, look, and iterate on the
numbers before handing the file over.

## 1. Identify the typeface FIRST

Stroke-width probing only tells you the **weight** — it cannot tell PingFang
from Noto from Hiragino, because at the same size all three give nearly the
same median stroke width. Identify by **glyph shape**.

`scripts/fontid.py` (exposed as `photoswap.py fontid`) does this:

1. Cut one character out of the original raster using its **ink bbox**, as a
   soft coverage map: `ink = (paper - pixel) / (paper - ink)`, paper = 95th
   percentile of the box, ink = 5th (self-calibrating).
2. Render the **same character** with each candidate font at each candidate
   size, cropped to **its own ink bbox**.
3. Align by sliding the candidate ±4 px in x and y; keep the best match.
4. Score = `0.7 * normalised cross-correlation + 0.3 * IoU`.

The correlation identifies the typeface — it measures **shape**. IoU punishes
a 1 px edge shift far harder than a human eye does, so it is the tie-breaker
and the report column, not the primary signal.

### The trap that hides the winner — ALIGN BY INK BBOX, NEVER force-resize

An earlier version resized every candidate glyph into a fixed 52×54 box before
comparing. **That is wrong for CJK.** Different faces give different glyph
widths for the same character (at ink height 45, 人 is 45 px wide in PingFang,
45 in Noto, 43 in Hiragino W3, 46 in STHeiti Medium). Forcing them into one
box distorts every candidate, so all of them score in a useless 0.49–0.71 band
and the true winner is invisible.

> **Rule: crop every glyph to its own ink bbox and align. Never force-resize
> to a common box.** A ranking where the top-12 scores are all within ~0.05 of
> each other means you force-resized, or your glyph boxes are wrong.

### Measured result — app screenshot (the font was NOT PingFang)

```
 score   corr    IoU  size  face                            font
 0.613  0.690  0.434    49  Noto Sans CJK SC Regular        NotoSansCJKsc-Regular.otf
 0.580  0.653  0.409    50  Noto Sans CJK SC Regular        NotoSansCJKsc-Regular.otf
 0.535  0.603  0.376    52  PingFang SC Medium              PingFang.ttc
 0.520  0.592  0.354    50  PingFang SC Regular             PingFang.ttc
```

Winner: **Noto Sans CJK SC Regular @ 49 px** for the dark rows, 46 px for the
white-on-green 专业 row. Noto Sans CJK SC and Source Han Sans SC have
**identical outlines**, so either file works. macOS does **not** ship them —
download the OTF from GitHub (`notofonts/noto-cjk`) or ask the user for the
file, and put it in the working directory (fontid searches there first).

### Practical notes on `fontid`

- Give it **2-3 glyphs**, simple common characters (`人`, `工`, `2`). Complex
  glyphs share strokes with neighbours and pollute the cut.
- Each `--glyph` box must **hug that character's ink bbox exactly**. A box
  including a neighbour, a rule, or a background gradient corrupts the score.
- `--size` is a comma-separated list of sizes to try; omit it and the tool
  derives candidates from the original's ink height (±8).
- The ranking must **separate** — the winner visibly ahead of the runner-up.
- `--json` gives machine-readable output for scripted pipelines.

### The matcher fetches the missing open-source families

The images this skill is used on are often web pages, and most Chinese web
pages are set in **Noto Sans CJK / Source Han Sans** — which are **not**
installed by default on macOS or Windows. A matcher that only knows the
system faces would answer *"PingFang SC Medium"* for such an image: a
plausible-looking but wrong answer that no later tuning can fix.

So `fontid` downloads the open-source families it is missing (into
`scripts/fonts/`, cached after the first run) and includes them in the
comparison. Use `--no-download` to turn that off, `--font` to point at your
own copies, and `--font-dir` to choose where they land.

Measured result on the reference screenshot with the fetch enabled:

```
score   corr    IoU  size  face                            font
 0.611  0.689  0.429    49  Source Han Sans SC Regular      SourceHanSansSC-Regular.otf
 0.611  0.689  0.428    49  Noto Sans CJK SC Regular        NotoSansCJKsc-Regular.otf
 0.596  0.664  0.438    49  Source Han Sans SC Medium       SourceHanSansSC-Medium.otf
 ...                                       (PingFang ranks far below)
```

## 2. Erase the old text — the discipline that decides acceptance

> **The erase region must hug the INK BBOX of exactly the characters being
> replaced. Never erase a whole text-row band.**

### The destroyed-background bug (this caused a rejected delivery)

The card's 班级 row erase region was `2178,1800,2814,2108`, but the real ink
of 「人力資源」 ends at **y=1979**. The extra band contained the card's own
blue background gradient *and* the 「XX学院」 watermark. The watermark is dark
enough that the ink mask mistook it for text, so the inpaint replaced it with
flat grey paper — the user saw a hard-edged grey rectangle where the
background should have been.

> **A background watermark is dark enough to be mistaken for ink.** Measure
> the ink bbox of the specific characters, erase that, and leave the
> watermark where it is.

### Per-channel fill — never fill from luminance

The fill was computed on the **luminance** image and written back to all three
RGB channels, turning the card's cool blue paper (155,167,176) into neutral
grey (165,165,165) — a beige ghost of the old strokes.

> **Fills must be PER-CHANNEL.** Compute the fill colour from the RGB
> channels (median per channel), never from luminance, or every coloured
> paper turns grey.

### Measure column groups at a LOW threshold

A threshold-130 column scan cut the last glyph at x=2749 when it actually
reaches **x=2805**, leaving 56 px of the old glyph unerased — a visible dark
stub. **Re-measure column groups at threshold 120.** Dark ink on light paper
is detected too late at high thresholds, and the leftover stub reads as a
smudge.

### Choosing the erase method

| background behind the text | method |
|---|---|
| watermark, seal, fold, colour band, gradient | `--erase inpaint` |
| flat UI (screenshot), plain form, uniform paper | `--erase bg` |
| photo of a glossy card with a big seal | `--erase inpaint`, `--ink-thresh 0.99` (the seal is dark too — **check the mask visually**) |

- `--erase inpaint` **(default)** — detect only the ink pixels and fill them
  from the surrounding paper. Any watermark, seal, fold, colour band or
  gradient behind the text **stays exactly where it was**.
- `--erase bg` — rebuild the whole strip from a per-column vertical median
  (percentile 70 over a ±110 px window) and feather the edges.
  **It NEVER works on a UI screenshot**: the ±110 px vertical window is
  taller than a 45 px text row, so the median follows the text itself and
  nothing is erased — the new text is drawn on top of the old one.

Inpaint tuning: `--ink-thresh 0.95 --min-run 3 --grow 2`. The threshold is a
fraction of the paper level — 0.95 catches the soft blur halo of the strokes,
which is what removes the ghost of the old text. `--grow N` dilates the
detected mask by N px so the halo is definitely covered. Too low (0.75) and the
halo survives as a ghost; too high (0.99) and you eat the paper.

> **Two more lessons.** (a) A percentile-based background rebuild cannot
> remove a large *localised* feature such as a watermark seal — it only
> rebuilds the per-column level; if a ghost band remains, switch to inpaint.
> (b) The erase region must cover the **WHOLE** old text: measure the
> original's ink bbox first, and if the new text is wider, widen the region —
> otherwise the old strokes that stick out remain and read as doubling.

### The `--dark-thresh 0` trap — "off" must mean `None`

`--dark-thresh` is an **absolute** luminance threshold, and the CLI's default
is `0`, which means "off". Inside `ink_mask()` a non-`None` `dark_thresh` turns
the test into `reg < 0` — **nothing is detected, nothing is erased**, and the
old text survives to collide with the new text (the "数字技融学院" garbling).

So the CLI must translate the sentinel:

```python
dark_thresh = args.dark_thresh or None   # 0 => None => paper-relative test
m = M.ink_mask(im, box, paper, thresh=args.ink_thresh,
               min_run=args.min_run, grow=args.grow, light=light,
               dark_thresh=dark_thresh)
```

**Symptom:** the output shows the new text superimposed on the old one, and
the ink statistics of the edited row look fine. **Proof:** spy on the image
handed to the renderer — if its minimum is still the ink colour (51 on the
reference screenshot), the erase did not happen.

### `--extra` — re-lay the neighbours of a row

When the new value is longer, everything after it in the same row has to
move: the `|` separator and the second value. `--extra` redraws them:

```
--extra "text@x,size"        # absolute x
--extra "text@-gap,size"     # gap px after the previous element's ink
--extra "text@x,size@gap"    # absolute x, then leave `gap` px before the next
```

The first `--extra` is placed `gap` px after the ink of the new value; every
following one is placed `gap` px after the previous element. A **negative** x
is relative to the previous element (`-53` = 53 px after it).

Measured on the reference screenshot:

```
--text "人工智能技术应用"  --extra "|@-53,46"  --extra "普通全日制@-53,46"
  ->  separator at x=528, 普通全日制 at x=583   (matches the original spacing)
```

**The erase region must cover the OLD separator and the OLD second value as
well**, or they are doubled by the new ones. In the reference case the
profession row's region had to grow from `105,1128,505,1190` to
`105,1128,730,1190` because the old 普通全日制 ends at x=715.

## 3. Render the ink

The model is exactly this, and nothing else:

```
alpha = blur(feather(glyph_mask), sigma)
out   = paper * (1 - alpha) + ink * alpha
out  += grain * alpha
```

A photographed printed character is a crisp glyph convolved with the camera
point-spread function, composited onto paper, with the paper's own texture on
top. The measured profile of one original stroke (paper ≈ 176, core ≈ 44):

```
178 175 175 175 176 179 188 191 189 | 181 169 164 163 153 138 118 94 72 55 | 44 | 47 67 85 96 109 132 162 173 171 175
```

ONE smooth monotone ramp on each side of a solid core, ~9-10 px per side.
There is **no** second halo, **no** ragged edge, **no** flying white.

- `--sigma` is the camera PSF. Measure it, do not guess: cut a profile across
  a single clean stroke of the original and compare it with the same cut of
  your render, then pick the sigma whose profile matches.
  `psf_sigma()` in `measure.py` automates this (10-90 % ramp / 2.56).
- `--ink` is the ink colour. Real ink is near black but the *core* of a
  blurred stroke is diluted: a 7 px stroke blurred with sigma 2.4 peaks at
  only ~0.55 alpha, so plain compositing leaves a grey core. Darken the ink
  colour (e.g. 26 26 26) and/or add `--contrast` (a soft knee
  `a + c*a*(1-a)`) to push the covered part of the ramp back to solid.
- Grain: the photo's own high-frequency residual is added on top of the ink,
  scaled by alpha. Ink printed on paper carries the paper's texture.
  **On a flat UI screenshot there is no grain** — the residual there is just
  the anti-aliasing of the ORIGINAL text, and adding it on top of the new
  text makes the glyphs look doubled and fuzzy. `--grain auto` (the default)
  turns it off when the paper is pure white or pure black; `--grain off`
  forces it.

## 4. Photo vs screenshot — exact values

| | photographed print | screen capture |
|---|---|---|
| `--sigma` | 2.4 (from the measured profile) | **0.15** |
| `--edge` | 0.6 | **0.5** |
| `--grain` | on (the paper texture) | **off** |
| `--ink` | 26 26 26 (near black) | the UI's own text colour, e.g. 51 51 51 |
| `--erase` | inpaint | inpaint (never `bg`) |
| blur source | camera PSF | raster anti-aliasing only |

A UI screenshot has **no camera PSF and no paper grain**. `sigma 0.15` gives
just enough softness to avoid the vector-crisp look while keeping the edges
as sharp as the original UI text.

## 5. Align

- `--align-x` = the x of the original's **left ink edge**. Do not use the left
  edge of the region you erased — use the original's ink bbox.
- Vertically, measure the ink extent of each original character (threshold at
  ~30 % of paper level, require ≥ 3 dark pixels per row so a watermark seal
  cannot pollute the result) and match the top and bottom. A text block that
  is 5-9 px off is instantly visible.
- `render_text()` supports `valign="top" | "center" | "bottom"`. Use
  `valign="top"` when you know the exact row the ink must start on — the
  default "center" places the ink in the middle of the box and moves it when
  the box is shorter than the glyph.

### When the new text is longer than the old one

It pushes into whatever follows it. **Re-lay out the whole row in ONE
operation**: erase the row band once, then render every part. Erasing and
re-rendering each element separately leaves seams and overlapping remnants.
Measure the following element (a separator bar, the next column) and preserve
the original gaps. Case study: the 专业 text was 269 px wide and the new one
361 px, so the `|` separator moved from x=438 to x=530 and 普通全日制 from
x=493 to x=586, keeping the original 54 px / 53 px gaps.

## 6. Light text on a coloured background

White text on a green/blue panel is the inverse case: the ink is BRIGHTER
than the background.

- `--light-ink` flips every detection test: the ink mask becomes
  `reg > background + (255-background)*thresh`, and the background level is
  taken as the 12th percentile (the panel colour) instead of the 88th.
- Use a LOWER `--ink-thresh` (0.6) than for dark ink — the anti-aliased
  edge of a white glyph on green is a wide soft ramp, and a 0.95 threshold
  leaves visible fragments of the old glyph.
- `--ink 255 255 255` and `--contrast 0.8` so the stroke core reaches pure
  white instead of a pale green-white.
- `--grain off` is essential: the high-frequency residual of a UI image is the
  anti-aliasing of the ORIGINAL glyphs, and adding it over the new white text
  turns the text grey and patchy.

## 7. Verify before delivering

- `compare` the original and the result at 2-3× zoom.
- Re-run `ink_stats` on the edited region and compare with the original:
  stroke width, core darkness, coverage.
- **Check background integrity**: diff the output against the input and
  confirm only the intended row bands changed. On the app screenshot exactly
  4 bands changed (1133-1184, 1844-1890, 1964-2010, 2083-2129), 50637
  changed pixels, everything else byte-identical. Any other changed pixel
  means the erase bled outside the ink bbox.
- Look for: ghost of the old text, a hard-edged rectangle where the
  background was flattened, seams at the erase boundary, a wrong baseline, an
  ink colour too grey or too black, a sharp-edged glyph, a stroke that looks
  thicker than its neighbours.
- **ALWAYS render a side-by-side crop and look at it.** A fully green test
  suite once passed on an image where the new text was superimposed on the
  old one. Numeric checks (ink core, changed bands, coverage) all stayed
  correct while the picture was broken.
- **Compare the rendered text against a reference render of the same string.**
  Render the expected string with the same font, size, target box, align and
  valign, then take the **IoU of the two ink masks** (threshold 200 dark /
  250 light). It must be ≈1.0, and `(edited & ~expected)` must be 0 — any
  ink there is the OLD text that survived the erase.
  - Use the mask **IoU**, not a normalised correlation: over a sparse binary
    mask the correlation collapses to ~0.14 even for two *identical* masks.
  - The reference render must use the **same target box** the CLI uses:
    `(align_x, box_y, align_x + (box_x1 - box_x0), box_y1)`.
- When you paste an edited strip back into the accumulated image, the paste
  crop must be **wider than the erase region**, or the text is truncated at
  the crop edge (the 班级 row lost its 班 this way).

## What NOT to do (each of these was tried and failed)

| don't | because | instead |
|---|---|---|
| resize candidate glyphs into a fixed box before matching | every CJK candidate scores in a useless band; the winner is invisible (§1) | align by ink bbox, never force-resize |
| erase a whole text-row band instead of the characters' ink bbox | the gradient and the watermark get flattened into a grey rectangle (§2) | erase only the characters' ink bbox |
| fill from the luminance image and write back to all three RGB channels | coloured paper turns neutral grey; old strokes ghost (§2) | fill PER-CHANNEL |
| measure column groups at a high threshold (130) | the last glyph is cut short, leaving a dark stub (§2) | re-measure at threshold 120 |
| use `--erase bg` on a screenshot | the ±110 px median window is taller than the text row, so nothing is erased (§2) | `--erase inpaint` |
| pass `--dark-thresh 0` straight into `ink_mask()` | 0 is the "off" sentinel but `ink_mask` reads any non-None value as an absolute threshold, so the test becomes `reg < 0` and NOTHING is erased (§2) | translate it: `args.dark_thresh or None` |
| trust a green test suite | one run passed every numeric check while the new text was superimposed on the old one (§7) | render a side-by-side crop and LOOK at it |
| compare two ink masks with a normalised correlation | over a sparse binary mask it gives ~0.14 even for identical masks (§7) | use the mask IoU |
| assume a UI screenshot uses PingFang | it was Noto Sans CJK SC Regular | always run `fontid` (§1) |
| judge the typeface from stroke width alone | that tells you the weight, never the face (§1) | identify by glyph shape |
| spread the mask and multiply by noise | a pale offset copy (ghosting) *and* holes punched through the strokes | blur the crisp mask only |
| add a separate soft halo layer | a visible second, lighter copy of the character behind it | one monotone ramp per side (§3) |
| add flying-white speckles inside the stroke | the stroke breaks into dashes | keep a solid core |
| dilate the glyph to fatten strokes | reads as a marker pen | use the face's natural weight |
| infer the model from region-wide statistics | row-run widths on a diagonal stroke suggest a "thin core + wide halo" that is not there | cut a profile across ONE clean stroke |

## Failure catalogue

The full catalogue (16 rows) is in `references/parameters.md` §11. The rows
that decide acceptance:

| symptom | cause | fix |
|---|---|---|
| all candidate fonts score within 0.05 of each other | candidates were force-resized into a common box | align by ink bbox, never force-resize |
| the identified face looks wrong | glyph boxes not tight / include a neighbour | cut each box to that character's ink bbox exactly |
| hard-edged grey rectangle where the background was | the erase band swallowed a watermark; the mask treated it as ink | erase only the characters' ink bbox; `--erase inpaint` |
| the paper turned neutral grey, old strokes ghosted | the fill was computed on luminance and written to all RGB channels | fill PER-CHANNEL (median per channel) |
| a dark stub of the old character remains | column groups measured at too high a threshold (130) | re-measure at threshold 120 |
| the new text sits on top of the old one (screenshot) | `--erase bg`: the ±110 px median window follows the text | use `--erase inpaint` on screenshots |
| pale offset copy behind the glyph (ghosting) | the mask was spread and then multiplied by noise | never roughen a mask multiplicatively — blur the crisp mask only |
| strokes broken into dashes / a marker-pen look | flying-white noise, or the glyph was dilated | remove the noise; use the face's natural weight |
| the block sits 5-10 px too high | baseline taken from the PIL text box, not the original ink | measure the original ink extent per character and match it |
| old text still faintly visible | the ink mask missed the stroke's blur halo | raise `--ink-thresh` towards 0.95-0.99 |
| new text too grey | alpha never reaches 1 on a thin blurred stroke | darker `--ink`, or `--contrast 0.4-0.8` |
| the new text is razor sharp | no PSF | `--sigma` from the measured profile |
| new text grey / patchy on a coloured panel | the old glyphs' anti-aliasing was added on top of the new ink | `--grain off` |

## Fonts on macOS

System Chinese fonts live under
`/System/Library/AssetsV2/com_apple_MobileAsset_Font8/*/asset/AssetData/`.
Useful ones: `PingFang.ttc` (faces 3/7/11 = SC Regular / Medium / Semibold),
`Kaiti.ttc` (0 Kaiti SC Regular, 3 Kaiti SC Bold, 5 Kaiti SC Black),
`Songti.ttc`. `face_names()` lists them.

**Noto Sans CJK SC / Source Han Sans SC are NOT on macOS** — download the OTF
from GitHub (`notofonts/noto-cjk`) or ask the user for the file. Put it in
the working directory; `fontid` checks the working directory first.

## Case studies

| case | face | size | source |
|---|---|---|---|
| photographed student card (4032×3024), 学院 row | Kaiti SC Bold (Kaiti.ttc face 3) | 160 | photo |
| app screenshot (学信网), dark rows | Noto Sans CJK SC Regular | 49 | screenshot |
| app screenshot, 专业 row (white on green) | Noto Sans CJK SC Regular | 46 | screenshot |

Measured verification numbers for both cases, the full parameter tables and
the card's ink bboxes are in `references/parameters.md`.

## Files

- `scripts/photoswap.py` - CLI: `fontid`, `probe`, `edit`, `compare`, `verify`
- `scripts/fontid.py` - typeface identification by per-glyph shape matching
- `scripts/measure.py` - paper level, ink stats, stroke width, PSF sigma,
  background rebuild, ink mask, inpaint
- `scripts/ink.py` - the ink model and the renderer
- `references/parameters.md` - parameter cheat sheet, measured case studies,
  fontid tables, failure catalogue

Requires only `numpy` + `Pillow` (no scipy/cv2 needed).

### The `edit` arguments that matter

| flag | default | meaning |
|---|---|---|
| `--region` | - | x0,y0,x1,y1 of the old text; must cover it completely, and nothing more |
| `--text` / `--font` / `--face` / `--size` | - | the new text; the face and size from `fontid` |
| `--align-x` | 0 | the x of the original's left INK edge |
| `--valign` | center | `top` / `center` / `bottom` for the ink's vertical placement |
| `--sigma` | 2.4 | the camera PSF; **0.15** for a screen capture |
| `--edge` / `--gamma` / `--contrast` | 0.6 / 0.92 / 0.0 | anti-alias radius, alpha ramp gamma, stroke-core knee |
| `--ink` | 20 20 20 | the ink colour |
| `--grain` | auto | `on` / `off` / `auto` (auto disables it on screenshots) |
| `--light-ink` | off | the text is brighter than the background |
| `--erase` | inpaint | `inpaint` (keeps watermarks) / `bg` (rebuilds the paper) |
| `--ink-thresh` / `--min-run` / `--grow` | 0.95 / 3 / 2 | ink detection threshold, min dark run, mask dilation |
| `--dark-thresh` | 0 | ABSOLUTE luminance threshold for ink detection; 0 = off (use it when the region holds a watermark or a rule that must not be eaten) |
| `--fit` | warn | `warn` / `shrink` / `off` — warns when the new text is wider than the old ink; `shrink` reduces the size until it fits |
| `--extra` | - | repeatable; re-lays a neighbouring element of the same row, e.g. `--extra "\|@-53,46"` |
| `--no-per-channel` | off | never use this on coloured paper (a luminance-only fill turns blue paper grey) |

Full defaults and the `fontid` flag list: `references/parameters.md` §1 and §7.