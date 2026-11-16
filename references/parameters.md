# photoswap-text — parameter cheat sheet

## 1. Font identification (`photoswap.py fontid`)

"Which font is this?" decides whether a text swap looks native. Stroke-width
probing only tells you the *weight* — it cannot tell PingFang from Noto from
Hiragino, because at the same size all three produce nearly the same median
stroke width. Identify by **glyph shape**.

### Method

1. Cut one character out of the original raster using its **ink bbox**, as a
   soft coverage map: `ink = (paper - pixel) / (paper - ink)`. The paper level
   is the 95th percentile of the box, the ink level the 5th — self-calibrating.
2. Render the **same character** with each candidate font at each candidate
   size, cropped to **its own ink bbox**.
3. Align by sliding the candidate ±4 px in x and y; keep the best match.
4. `score = 0.7 * normalised cross-correlation + 0.3 * IoU`.

The **correlation** is the identifying signal (it measures shape). IoU punishes
a 1 px edge shift much harder than a human eye does, so it serves as the
tie-breaker and the reporting column.

### THE TRAP — align by ink bbox, never force-resize

An earlier version resized every candidate into a fixed **52×54** box before
comparing. That is wrong for CJK: different faces give different glyph widths
for the same character.

| face | ink height | ink width of 人 |
|---|---|---|
| PingFang SC | 45 | 45 |
| Noto Sans CJK SC | 45 | 45 |
| Hiragino Sans GB W3 | 45 | 43 |
| STHeiti Medium | 45 | 46 |

Forcing them into one box stretches or squashes every candidate, so all of
them land in a useless **0.49–0.71** score band and the true winner is
invisible. **Crop to each glyph's own ink bbox and align. Never force-resize.**

### CLI

```bash
cd ~/.dsh/skills/photoswap-text/scripts

python3 photoswap.py fontid shot.png \
        --glyph "人:664,2083,709,2128" \
        --glyph "2:555,2083,578,2128" \
        --size 45,46,47,48,49,50,51,52 \
        --top 12
```

| flag | default | meaning |
|---|---|---|
| `--glyph` | required | `char:x0,y0,x1,y1`, repeatable; the box must hug that glyph's ink bbox |
| `--font` | auto | candidate font file, repeatable; default = local project fonts + macOS system CJK faces |
| `--project-dir` | cwd | extra directories searched for local Noto/Source Han OTFs |
| `--size` | derived | comma-separated point sizes to try; omitted = derived from the original's ink height (±8) |
| `--thresh` | 200 | luminance below which a pixel counts as ink (dark ink) |
| `--search` | 4 | translation search radius, in px |
| `--top` | 12 | how many candidates to report |
| `--json` | off | machine-readable output (score, corr, iou, size, face, font, per-glyph IoU) |
| `--no-download` | off | do not fetch the open-source families that are missing |
| `--font-dir` | `scripts/fonts` | where a fetched font is stored |

### The missing open-source families

`fontid` downloads the families below when they are not already on the
machine, so that a web-page image (usually Noto / Source Han) is compared
against its real face instead of against the nearest system face.

| family | file | source |
|---|---|---|
| Noto Sans CJK SC Regular / Light / Medium | `NotoSansCJKsc-{Regular,Light,Medium}.otf` | github.com/notofonts/noto-cjk |
| Source Han Sans SC Regular / Light / Medium | `SourceHanSansSC-{Regular,Light,Medium}.otf` | github.com/adobe-fonts/source-han-sans |

The files are cached in `scripts/fonts/` after the first download. Noto and
Source Han carry the SIL OFL 1.1 license; nothing proprietary is ever
redistributed.

**Without this step the answer is wrong in a way that looks right**: on the
reference screenshot, with no Noto on the machine, the matcher reports
*PingFang SC Medium @50* (score 0.577); with Noto present it reports
*Noto Sans CJK SC Regular @49* (score 0.611). The outlines differ, so the
substituted text reads as a different typeface no matter how the blur is
tuned.

### Measured result — app screenshot (学信网)

```
 score   corr    IoU  size  face                            font
 0.613  0.690  0.434    49  Noto Sans CJK SC Regular        NotoSansCJKsc-Regular.otf
 0.580  0.653  0.409    50  Noto Sans CJK SC Regular        NotoSansCJKsc-Regular.otf
 0.535  0.603  0.376    52  PingFang SC Medium              PingFang.ttc
 0.520  0.592  0.354    50  PingFang SC Regular             PingFang.ttc
```

| candidate | score | corr | IoU | size | face |
|---|---|---|---|---|---|
| winner | 0.613 | 0.690 | 0.434 | 49 | Noto Sans CJK SC Regular |
| runner-up (same face) | 0.580 | 0.653 | 0.409 | 50 | Noto Sans CJK SC Regular |
| best PingFang | 0.535 | 0.603 | 0.376 | 52 | PingFang SC Medium |
| second PingFang | 0.520 | 0.592 | 0.354 | 50 | PingFang SC Regular |

**The font was NOT PingFang.** It is **Noto Sans CJK SC Regular @ 49 px** for
the dark rows, **46 px** for the white-on-green 专业 row.

Notes:

- Noto Sans CJK SC and Source Han Sans SC have **identical outlines** — either
  file produces the same render.
- macOS does **not** ship Noto/Source Han. Download the OTF from GitHub
  (`notofonts/noto-cjk`, or the Source Han Sans release) or ask the user for
  the file. Put it in the working directory; `fontid` searches the working
  directory first.
- A healthy ranking **separates**: the winner should be clearly ahead of the
  runner-up. If the top-12 scores are all within ~0.05, the glyph boxes are
  wrong (too loose, or they include a neighbouring character / a rule).

## 2. Measured values from the reference case (photographed card)

Photographed student card (4032×3024), 学院 row = 数字金融学院, replaced with
数字技术学院; 班级 row = 人力資源 (traditional), replaced with 人工智能.

### Original photo measurements

| quantity | how measured | 学院 row | 班级 row |
|---|---|---|---|
| paper level | median of the clean band around the glyphs | 191.7 | 171 |
| ink core luminance | 5th percentile inside the ink | 11.3 | ~5 |
| stroke width | median dark-run length per row | 18 px | 18 px |
| ink coverage (paper×0.75) | fraction of dark pixels in the box | 0.424 | — |
| per-char ink height | rows with ≥3 dark px, threshold <100 | 133–147 | 110–160 |
| left ink edge | x of the first dark column | 1881 | 2182 |
| top ink edge | y of the first dark row | 1531 | 1841 |

### Ink bboxes on the card (4032×3024)

学院 row 「数字金融学院」 — ink rows **1523..1674**:

| char | column group |
|---|---|
| 数 | 1881–2025 |
| 字 | 2043–2180 |
| 金 | 2198–2345 |
| 融 | 2360–2502 |
| 学 | 2520–2652 |
| 院 | 2683–2815 |

班级 row 「人力資源」 (traditional) — ink rows **1823..1979**:

| char | column group |
|---|---|
| 人 | 2186–2344 |
| 力 | 2357–2483 |
| 資 | 2517–2659 |
| 源 | 2676–**2805** |
| 3 | 2839–2893 |
| 班 | 2907–2949 |

> **The 源 glyph reaches x=2805, not x=2749.** A threshold-130 column scan
> cut it at 2749 and left 56 px of the old glyph unerased — a visible dark
> stub. **Re-measure column groups at threshold 120.**

### Colours on the card

| element | RGB |
|---|---|
| paper | (155, 167, 176) — cool blue |
| ink core | (22, 25, 33) |
| ink halo | (78, 85, 93) |
| watermark (darkest) | 113 |
| printed ink (darkest) | 0 |

The threshold **105–115** separates printed ink from the watermark.

### Chosen render parameters

```
font          Kaiti.ttc face 3  (Kaiti SC Bold)
size          160
sigma         2.4
edge          0.6      (raster anti-alias)
gamma         0.92
contrast      0.0
ink           (26, 26, 26)
grain         photo's own high-frequency residual, scaled by alpha
```

### Face matching table (Kaiti.ttc)

| face | name | natural stroke width at size 160 |
|---|---|---|
| 0 | Kaiti SC Regular | 12 |
| 3 | Kaiti SC Bold | 15 |
| 5 | Kaiti SC Black | 19 |

The original measured 18 px → Bold (plus the visual check: rounded brush blob
at the top of 人 and the broad bottom-right sweep are Bold's terminals).

PingFang.ttc for the app screenshot: face 3 = SC Regular, 7 = SC Medium,
11 = SC Semibold. (Note: the app screenshot's actual face is Noto Sans CJK SC
— see §1.)

## 3. Erase discipline — the three lessons that caused a rejected delivery

### 3a. The erase region must hug the ink bbox (never erase a whole row band)

The card's 班级 row erase region was `2178,1800,2814,2108`, but the real ink
of 「人力資源」 ends at **y=1979**. The extra band contained the card's blue
background gradient *and* the 「XX学院」 watermark. The watermark is dark
enough that the ink mask mistook it for text, so the inpaint replaced it with
flat grey paper — the user saw a **hard-edged grey rectangle**.

> **A background watermark is dark enough to be mistaken for ink.**
> Erase only the ink bbox of exactly the characters being replaced. Never
> erase a whole text row band.

### 3b. Per-channel fill — never fill from luminance

The fill was computed on the **luminance** image and written back to all
three RGB channels, turning the card's cool blue paper (155,167,176) into
neutral grey (165,165,165) — a beige ghost of the old strokes survived.

> **Fills must be PER-CHANNEL.** Compute the fill colour as the median of
> each RGB channel separately, never from luminance.

### 3c. Measure column groups at threshold 120

See the card ink-bbox table above: threshold 130 cut 「源」 at x=2749 instead
of x=2805, leaving 56 px of the old glyph as a visible dark stub.

### Choosing the erase method

| background behind the text | method |
|---|---|
| watermark, seal, fold, colour band, gradient | `--erase inpaint` |
| flat UI (screenshot), plain form, uniform paper | `--erase bg` |
| photo of a glossy card with a big seal | `--erase inpaint`, `--ink-thresh 0.99` (the seal is dark too — check the mask visually) |

Inpaint tuning: `--ink-thresh 0.95 --min-run 3 --grow 2`. The threshold is a
fraction of the paper level; 0.95 catches the soft blur halo of the strokes,
which is what removes the ghost of the old text. Too low (0.75) and the halo
survives as a ghost; too high (0.99) and you eat the paper.

> A percentile-based background rebuild cannot remove a large *localised*
> feature such as a watermark seal — it only rebuilds the per-column level.
> If a ghost band remains in the erased area, switch to inpaint.

## 4. Light ink on a coloured panel

The green card's 专业 row is WHITE text on a green (52,193,139) panel.

```
--light-ink  --ink 255 255 255  --contrast 0.8
--ink-thresh 0.6  --grow 2  --sigma 0.15  --edge 0.4  --grain off
```

Why each value:

| value | reason |
|---|---|
| `--light-ink` | the ink mask test must be `reg > bg + (255-bg)*thresh`, not `< paper*thresh` |
| `--ink-thresh 0.6` | a white glyph on green has a wide anti-aliased ramp; 0.95 leaves fragments of the old glyph |
| `--grow 2` | swallows the soft edge of the old glyph |
| `--ink 255 255 255` | the stroke core must reach pure white |
| `--contrast 0.8` | the soft knee pushes the covered part of the ramp to alpha 1 |
| `--grain off` | the image's high-frequency residual IS the old glyphs' anti-aliasing; adding it over the new white text makes it grey and patchy |

### Detecting "this is a screenshot, not a photo"

`highfreq()` residual standard deviation: photo ≈ 5.0, screenshot ≈ 15.7.
`--grain auto` turns the grain off above 9.0 (and for pure white/black
backgrounds).

## 5. Re-laying out a row whose text grew

The 专业 row of the green card:

| element | original ink | new ink |
|---|---|---|
| 专业 value | 115..384 (人力资源管理, 269 px) | 115..476 (人工智能技术应用, 361 px) |
| `|` separator | 438..440, rows 1133..1183 | 530..533, rows 1132..1182 |
| 普通全日制 | 493..715 | 586..809 |

Gaps preserved: 54 px before the separator, 53 px after it. The `|` was
rendered at size 51 (the font's `|` at size 46 is only 46 px tall; the
original bar was 51 px).

Do it as ONE operation: erase the whole row band once with
`ink_mask(..., light=True)`, then re-render all three parts.

### 5a. Doing it from the CLI — `--extra`

The `edit` subcommand can re-lay the neighbours of the row in one pass:

```
--text "人工智能技术应用"
--extra "|@-53,46"        # 53 px after the ink of the new value
--extra "普通全日制@-53,46"  # 53 px after the separator
```

The cursor starts at the ink right edge of the new value
(`target[0] + new_w - 1`) and moves to `x + ew - 1` after each element.
A **negative** x is relative to the previous element. An optional `@gap` at
the end (`"text@x,size@gap"`) sets the gap to leave before the next element.

Measured result: separator at **x=528**, 普通全日制 at **x=583** — the same
layout the hand-written `edit_app.py` produced.

**The erase region must cover the OLD separator and the OLD second value**
or they are doubled by the new ones: for this row the region grew from
`105,1128,505,1190` to `105,1128,730,1190` (the old 普通全日制 ends at
x=715).

## 6. The app-screenshot case (学信网)

```
region 555,2078,861,2128   (the original ink bbox)
text   2026人工智能03班
font   NotoSansCJKsc-Regular.otf  (NOT PingFang), size 49
sigma 0.15  edge 0.5  grain off  ink 51 51 51
```

The original ink is 307 px wide at x 555-861; the new text is 409 px wide
because 人工智能 is four characters where 人资 was two, so the row simply
grows to the right — that is normal and matches the physical card.

Other rows of the same screenshot: 专业 `人力资源管理` → `人工智能技术应用`
(white on green, size 46); 分院/系所 `数字金融学院` → `数字技术学院`;
班级 `2026人资03班` → `2026人工智能03班`.

**Do not use `--erase bg` on a screenshot.** The vertical median window
(±110 px) is far taller than a 45 px text row, so the text is inside the
window and the median follows the text — nothing is erased and the new text
is drawn on top of the old one.

### Verification numbers (verified on the app screenshot)

| row | | 墨核 | 墨量 | 笔宽 (med) | mean |
|---|---|---|---|---|---|
| 班级 | ORIG | 51 | 0.241 | 4.0 | 5.5 |
| 班级 | EDIT | 51 | 0.249 | 4.0 | 5.8 |
| 系所 | ORIG | 51 | 0.292 | 3.0 | 5.3 |
| 系所 | EDIT | 51 | 0.266 | 3.0 | 5.1 |
| 专业 (white) | ORIG | 149 | 0.238 | 4.0 | 6.4 |
| 专业 (white) | EDIT | 145 | 0.229 | 4.0 | 5.9 |

### Background integrity (app screenshot)

Diffing the output against the input, only **4 row bands** changed:

```
1133..1184    1844..1890    1964..2010    2083..2129
```

Total **50637** changed pixels; everything else is byte-identical. Any other
changed pixel means the erase bled outside the intended ink bbox.

## 7. Defaults

```
--erase inpaint   --ink-thresh 0.95   --min-run 3   --grow 2
--sigma 2.4       --ink 20 20 20      --feather 26   --bg-half 110   --bg-pct 70
--edge 0.6        --gamma 0.92        --contrast 0.0  --grain auto
--dark-thresh 0   --fit warn
```

Screenshot overrides: `--sigma 0.15 --edge 0.5 --grain off`.

**`--dark-thresh 0` means "off"**, and the CLI has to translate it to `None`
before it reaches `ink_mask()`:

```python
dark_thresh = args.dark_thresh or None   # 0 => None => paper-relative test
```

A non-`None` `dark_thresh` is an **absolute** threshold, so passing 0 makes
the test `reg < 0`: nothing is detected, **nothing is erased**, and the old
text survives under the new one.

**`--fit warn`** compares the new text's ink width with the old slot's and
warns when the new one is wider; `--fit shrink` reduces the size until it
fits. It only warns — the erase region still has to be widened by hand.

## 8. Photo vs screen capture

| | photographed print | screen capture |
|---|---|---|
| `--sigma` | 2.4 (from the measured profile) | 0.15 |
| `--edge` | 0.6 | 0.5 |
| `--grain` | on (the paper texture) | off |
| `--ink` | 26 26 26 (near black) | the UI's own colour, e.g. 51 51 51 |
| `--erase` | inpaint | inpaint (**never `bg`**) |
| blur source | camera PSF | raster anti-aliasing only |
| font | from the card: Kaiti SC Bold @160 | from `fontid`: Noto Sans CJK SC Regular @49 |

`--grain auto` disables the grain when the paper level is >250 or <20, i.e. a
pure white / pure black UI.

## 9. Solving sigma by hand

1. Cut a profile across ONE clean, near-horizontal stroke of the original:
   `O[y0:y1, x]` for a vertical stroke, `O[y, x0:x1]` for a horizontal one.
   Pick a stroke in the middle of a character, not at an intersection.
2. Note the paper level and the core value.
3. Render the same glyph at a trial sigma and cut the same profile.
4. Compare the ramps. The number of samples from paper to core on each side
   is what decides the sigma — roughly `ramp_samples / 2.56` is the
   10-90 % sigma.

Measured example (学院 row, 字's top horizontal, vertical cut at x=2130):

```
original : 178 175 175 175 176 179 188 191 189 181 169 164 163 153 138 118 94 72 55 | 44 | 47 67 85 96 109 132 162 173 171 175
sigma 2.4: 176 174 170 164 154 141 125 106 88 70 56 44 36 31 28 26 26 27 30 36 44 55 ...
```

The ramp width matches; the core is lighter in the render because the blur
dilutes a thin stroke. Fix that with a darker `--ink`, not with a smaller
sigma.

## 10. Why `psf_sigma` on the photo reads higher than the render sigma

`psf_sigma()` measures the global blur of the photo (lens softness + JPEG +
noise + the print's own dot gain), which came out 4.30 on this card. The
render sigma that reproduces the *stroke profile* is 2.4. Match the profile;
treat the global number as a sanity bound.

## 11. Failure catalogue

| symptom | cause | fix |
|---|---|---|
| every candidate font scores within 0.05 of the others | candidates were force-resized into a common box | align by ink bbox, never force-resize |
| the identified face looks wrong | glyph boxes not tight / include a neighbour | cut each box to that character's ink bbox exactly |
| hard-edged grey rectangle where the background was | the erase band swallowed a watermark; the mask treated it as ink | erase only the characters' ink bbox; `--erase inpaint` |
| the paper turned neutral grey, old strokes ghosted | fill computed on luminance, written to all RGB channels | fill PER-CHANNEL (median per channel) |
| a dark stub of the old character remains | column groups measured at too high a threshold (130) | re-measure at threshold 120 |
| the new text sits on top of the old one (screenshot) | `--erase bg`: the ±110 px median window follows the text | use `--erase inpaint` on screenshots |
| pale offset copy behind the glyph (ghosting) | the mask was spread and then multiplied by noise | never roughen a mask multiplicatively — blur the crisp mask only |
| strokes broken into dashes | flying-white / rough noise punched holes | remove the noise entirely |
| a marker-pen look | the glyph was dilated | use the face's natural weight, pick the face by measured stroke width |
| the whole block sits 5-10 px too high | baseline taken from the PIL text box, not the original ink | measure the original ink extent per character and match it |
| old text still faintly visible | the ink mask missed the stroke's blur halo | raise `--ink-thresh` towards 0.95-0.99 |
| a vertical band ghost in the erased area | the percentile background rebuild cannot remove a localised feature | use `--erase inpaint` |
| blotchy / checkered erased area | raw diffusion output | the built-in 9×9 box blur over the filled pixels |
| new text too grey | alpha never reaches 1 on a thin blurred stroke | darker `--ink`, or `--contrast 0.4-0.8` |
| the new text is razor sharp | no PSF | `--sigma` from the measured profile |
| new text grey / patchy on a coloured panel | the old glyphs' anti-aliasing was added on top of the new ink | `--grain off` |
| the new text is superimposed on the old one, but the ink statistics look fine | `--dark-thresh 0` reached `ink_mask()` as an absolute threshold, so the test was `reg < 0` and NOTHING was erased | translate the sentinel: `args.dark_thresh or None` |
| the separator / second value of a row collides with the new text | the row's neighbours were not re-laid | `--extra "text@-gap,size"`, and widen the erase region to cover the OLD neighbours |
| the mask IoU is ~0.2 even though the two renders look identical | a normalised correlation over a sparse binary mask | use the mask **IoU** |
| the text is truncated at the right edge | the paste-back crop was narrower than the erase region | paste a crop that covers the whole new text |
| every numeric check passes but the picture is broken | the checks never compared the pixels against a reference render | render the expected string and compare the ink masks, and look at a side-by-side crop |
