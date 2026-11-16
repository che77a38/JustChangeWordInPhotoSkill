#!/usr/bin/env python3
"""Font identification by per-glyph IoU.

WHY THIS EXISTS
---------------
"Which font is this?" is the single question that decides whether a text
swap looks native.  Measuring stroke width only tells you the *weight*; it
cannot tell PingFang from Noto from Hiragino, because at the same size all
three produce nearly the same median stroke width.

The reliable method is to compare SHAPES:

  1. Cut one character out of the original raster, keeping only its ink
     pixels (a binary mask).
  2. Render the SAME character with a candidate font.
  3. Crop the candidate to its own ink bbox.
  4. Slide the candidate over the original by a few pixels in every
     direction and keep the best IoU.

Step 4 matters: a one-pixel offset drops the IoU by ~0.1 even for the right
font, because a CJK glyph has thin strokes where a half-pixel shift erases
a whole edge.

THE TRAP THAT COST US THE WINNER
--------------------------------
An earlier version of this tool resized every candidate into a fixed
52x54 box before comparing.  That is WRONG for CJK: different faces give
different glyph widths for the same character (at ink height 45 the 人 is
45 px wide in PingFang, 45 in Noto, 43 in Hiragino W3, 46 in STHeiti
Medium), so forcing them into one box stretches or squashes them and
every candidate scores in the same useless 0.49-0.71 band.  The true
winner (0.96) was invisible.

ALIGN BY INK BBOX.  NEVER force-resize.
"""
import os
import glob

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# candidate fonts
# --------------------------------------------------------------------------

# Local files (project-relative or absolute) that are checked first.
LOCAL_FONT_HINTS = [
    "NotoSansCJKsc-Regular.otf",
    "NotoSansCJKsc-Light.otf",
    "NotoSansCJKsc-Medium.otf",
    "SourceHanSansSC-Regular.otf",
    "SourceHanSansSC-Medium.otf",
    "SourceHanSansSC-Light.otf",
]

# macOS system fonts, by kind.
MAC_FONT_DIRS = [
    "/System/Library/AssetsV2/com_apple_MobileAsset_Font8",
    "/System/Library/Fonts",
    "/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
]

SYSTEM_FONT_HINTS = [
    # UI / sans
    ("PingFang.ttc", None),
    ("Hiragino Sans GB.ttc", None),
    ("STHeiti Medium.ttc", None),
    ("STHeiti Light.ttc", None),
    ("STXihei.ttf", None),
    ("Hei.ttf", None),
    ("Lantinghei.ttc", None),
    ("LiHeiPro.ttc", None),
    ("Arial Unicode.ttf", None),
    # serif
    ("Songti.ttc", None),
    ("STSong.ttf", None),
    ("STFangsong.ttf", None),
    # brush / rounded
    ("Kaiti.ttc", None),
    ("STKaiti.ttf", None),
    ("Yuanti.ttc", None),
    ("STYuanti.ttf", None),
]

# --------------------------------------------------------------------------
# open-source CJK families that are NOT installed by default and therefore
# have to be downloaded when the image was made with them.
#
# These are the families that show up in web pages and in other people's
# designs.  `fontid` can only match a face it has the actual font file for -
# if the original was set in Noto Sans CJK and Noto is not on the machine,
# the tool would happily answer "PingFang" (the nearest system face) and the
# swap would be subtly wrong.  So the tool says so instead of guessing.
# --------------------------------------------------------------------------

# family -> (download url, file name, faces)
DOWNLOADABLE_FAMILIES = {
    "NotoSansCJKsc-Regular": (
        "https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/"
        "NotoSansCJKsc-Regular.otf",
        "NotoSansCJKsc-Regular.otf",
        ["Noto Sans CJK SC Regular"],
    ),
    "NotoSansCJKsc-Light": (
        "https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/"
        "NotoSansCJKsc-Light.otf",
        "NotoSansCJKsc-Light.otf",
        ["Noto Sans CJK SC Light"],
    ),
    "NotoSansCJKsc-Medium": (
        "https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/"
        "NotoSansCJKsc-Medium.otf",
        "NotoSansCJKsc-Medium.otf",
        ["Noto Sans CJK SC Medium"],
    ),
    "SourceHanSansSC-Regular": (
        "https://github.com/adobe-fonts/source-han-sans/raw/release/OTF/"
        "SimplifiedChinese/SourceHanSansSC-Regular.otf",
        "SourceHanSansSC-Regular.otf",
        ["Source Han Sans SC Regular"],
    ),
    "SourceHanSansSC-Light": (
        "https://github.com/adobe-fonts/source-han-sans/raw/release/OTF/"
        "SimplifiedChinese/SourceHanSansSC-Light.otf",
        "SourceHanSansSC-Light.otf",
        ["Source Han Sans SC Light"],
    ),
    "SourceHanSansSC-Medium": (
        "https://github.com/adobe-fonts/source-han-sans/raw/release/OTF/"
        "SimplifiedChinese/SourceHanSansSC-Medium.otf",
        "SourceHanSansSC-Medium.otf",
        ["Source Han Sans SC Medium"],
    ),
}

# Faces we care about in a .ttc collection, keyed by face-name keywords.
# A face whose name contains none of these is skipped.
WANTED_FACE_KEYWORDS = [
    "Regular", "Medium", "Bold", "Semibold", "Light", "Black", "Thin",
    "W3", "W4", "W6", "PingFang", "Kaiti", "Hiragino", "Hei", "Song",
    "Noto", "Source Han",
]


def find_system_fonts(names=None):
    """Locate system font files by name.  Returns a list of paths."""
    names = names or [n for n, _ in SYSTEM_FONT_HINTS]
    out = []
    for n in names:
        hits = []
        for d in MAC_FONT_DIRS:
            if os.path.isdir(d):
                hits += glob.glob(os.path.join(d, "**", n), recursive=True)
        if hits:
            out.append(sorted(hits)[0])
    return out


def find_local_fonts(extra_dirs=()):
    """Locate open-source CJK fonts shipped in the working project.

    Searched, in order:
      1. the current working directory
      2. `scripts/fonts/` - where `photoswap.py fontid` caches the families it
         downloads
      3. the skill root (one level above `scripts/`) - a font dropped next to
         SKILL.md is found without any extra flag
      4. every extra directory given on the command line
    """
    here = os.path.dirname(os.path.abspath(__file__))
    skill_root = os.path.dirname(here)
    dirs = [os.getcwd(), os.path.join(here, "fonts"), skill_root]
    dirs += list(extra_dirs)
    out = []
    for n in LOCAL_FONT_HINTS:
        for d in dirs:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                out.append(p)
                break
    return out


def fetch_font(url, filename, dest_dir=None):
    """Download an open-source CJK font file and return its path.

    Used by `photoswap.py fontid` so that a face which is not installed by
    default (Noto / Source Han) can still take part in the comparison.
    Returns None if the download fails - the caller then simply carries on
    without that family.
    """
    import urllib.request
    if dest_dir is None:
        dest_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "fonts")
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except Exception:
        return None
    dest = os.path.join(dest_dir, filename)
    if os.path.isfile(dest) and os.path.getsize(dest) > 100_000:
        return dest
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "photoswap-text/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    except Exception:
        return None
    # a GitHub "not found" page comes back as HTML
    if len(data) < 100_000 or data[:4] not in (b"OTTO", b"\x00\x01\x00\x00",
                                               b"true", b"ttcf"):
        return None
    try:
        with open(dest, "wb") as f:
            f.write(data)
    except Exception:
        return None
    return dest


def face_names(path, limit=64):
    """[(index, (family, style)), ...] for a .ttc / .otf."""
    names = []
    for i in range(limit):
        try:
            f = ImageFont.truetype(path, 20, index=i)
        except Exception:
            break
        try:
            names.append((i, f.getname()))
        except Exception:
            break
    return names


def _face_is_interesting(name):
    fam, style = (name + ("", ""))[:2]
    blob = f"{fam} {style}"
    return any(k.lower() in blob.lower() for k in WANTED_FACE_KEYWORDS)


# --------------------------------------------------------------------------
# glyph extraction
# --------------------------------------------------------------------------

def render_glyph_mask(text, font, canvas=(1200, 600), pad=80, thr=200):
    """Render `text` and return (mask, ink_w, ink_h).

    `mask` is a float32 0..1 coverage map cropped to the glyph's ink bbox.
    It is SOFT, not binary: the anti-aliased edge of the raster is kept as
    partial coverage, exactly like the original raster is.  Comparing a
    hard 0/1 render against a soft original systematically understates the
    IoU.
    """
    im = Image.new("L", canvas, 255)
    ImageDraw.Draw(im).text((pad, pad), text, font=font, fill=0)
    a = np.asarray(im, np.float32)
    ys, xs = np.nonzero(a < thr)
    if len(ys) == 0:
        return None, 0, 0
    sub = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    m = np.clip((thr - sub) / max(1.0, float(thr - 0)), 0.0, 1.0)
    return m, int(m.shape[1]), int(m.shape[0])


def cut_original_glyph(img_gray, box, thr=200):
    """Cut one glyph out of the original image.

    `box` is (x0, y0, x1, y1) and must hug the glyph's ink bbox.
    Returns a float32 0..1 coverage map (ink = 1) or None.

    The coverage is derived from the luminance: the paper is ~255 and the
    ink core is ~51, so `ink = (paper - pixel) / (paper - ink)`.  The
    paper level is taken as the 95th percentile of the box and the ink
    level as the 5th, which makes the normalisation self-calibrating.
    """
    a = np.asarray(img_gray, np.float32)
    x0, y0, x1, y1 = box
    reg = a[y0:y1, x0:x1]
    if reg.size == 0:
        return None
    paper = float(np.percentile(reg, 95))
    ink = float(np.percentile(reg, 5))
    if paper - ink < 10:
        # flat region: fall back to a binary cut
        m = (reg < thr).astype(np.float32)
        return m if m.sum() > 0 else None
    m = np.clip((paper - reg) / (paper - ink), 0.0, 1.0)
    # drop the near-paper noise floor
    m[m < 0.15] = 0.0
    return m if m.sum() > 0 else None


def _pad_to(mask, h, w):
    out = np.zeros((h, w), np.float32)
    out[:mask.shape[0], :mask.shape[1]] = mask
    return out


def _norm(m):
    """Zero-mean, unit-norm flatten of a mask (for correlation)."""
    v = np.asarray(m, np.float32).ravel()
    v = v - v.mean()
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-6 else v


def best_match(orig_mask, cand_mask, search=4, margin=None):
    """Best alignment of `cand_mask` over `orig_mask` within +/-`search` px.

    Returns a dict:
        {"iou": float, "corr": float, "dx": int, "dy": int}

    `iou`  - the intersection-over-union of the two ink masks.
    `corr` - the normalised cross-correlation of the two coverage maps.
             This is the more reliable score: IoU punishes a one-pixel
             edge shift much harder than a human eye does, while the
             correlation of the *shape* barely moves.

    `margin` is the slack around the original glyph, in px.  It must be
    large enough that a candidate whose ink bbox is a little bigger than
    the original's still fits.  Default: the candidate's own size + search.
    """
    if orig_mask is None or cand_mask is None:
        return {"iou": 0.0, "corr": 0.0, "dx": 0, "dy": 0}
    oh, ow = orig_mask.shape
    ch, cw = cand_mask.shape
    if margin is None:
        margin = max(ch, cw) + search + 2
    H = oh + 2 * margin
    W = ow + 2 * margin
    t = _pad_to(orig_mask, H, W)
    t[margin:margin + oh, margin:margin + ow] = orig_mask
    tsum = float(t.sum())
    tflat = _norm(t)
    best = {"iou": 0.0, "corr": -1.0, "dx": 0, "dy": 0}
    for dy in range(-search, search + 1):
        for dx in range(-search, search + 1):
            c = np.zeros((H, W), np.float32)
            y0 = margin + dy
            x0 = margin + dx
            if y0 < 0 or x0 < 0 or y0 + ch > H or x0 + cw > W:
                continue
            c[y0:y0 + ch, x0:x0 + cw] = cand_mask
            csum = float(c.sum())
            if csum == 0:
                continue
            inter = float((c * t).sum())
            union = csum + tsum - inter
            iou = inter / union if union > 0 else 0.0
            corr = float((_norm(c) * tflat).sum())
            if corr > best["corr"] or (corr == best["corr"] and iou > best["iou"]):
                best = {"iou": iou, "corr": corr, "dx": dx, "dy": dy}
    return best


def best_iou(orig_mask, cand_mask, search=4, margin=None):
    """Backwards-compatible wrapper around `best_match`."""
    return best_match(orig_mask, cand_mask, search, margin)["iou"]


# --------------------------------------------------------------------------
# the identification pass
# --------------------------------------------------------------------------

def _size_candidates(target_h, ink_h_at_size, lo=None, hi=None):
    """Sizes whose ink height would match the original's.

    `ink_h_at_size` is the ink height of the reference glyph rendered at
    size 100 (a linear function of the size for a fixed face).
    """
    if ink_h_at_size <= 0:
        return []
    want = target_h / ink_h_at_size * 100.0
    lo = lo if lo is not None else max(6, int(want) - 8)
    hi = hi if hi is not None else int(want) + 8
    return list(range(lo, hi + 1))


def identify(img, glyphs, fonts=None, sizes=None, thr=200, search=4,
             project_dirs=(), verbose=False):
    """Identify the font used for `glyphs` in `img`.

    Parameters
    ----------
    img      : PIL image (the original).
    glyphs   : list of dicts: {"char": "人", "box": (x0,y0,x1,y1)}.
               Boxes must hug each glyph's ink bbox.
    fonts    : list of font file paths.  Default: local project fonts +
               the macOS system Chinese faces.
    sizes    : explicit list of point sizes to try.  Default: derived from
               the original glyph's ink height.
    thr      : luminance below which a pixel counts as ink (dark ink).
    search   : translation search radius, in px.

    Returns a list of result dicts, best first:
        {"font": path, "index": face_idx, "face": (fam, style),
         "size": pt, "iou": float, "per_glyph": {char: iou}}
    """
    if not glyphs:
        return []
    if fonts is None:
        fonts = find_local_fonts(project_dirs) + find_system_fonts()
    # de-duplicate, keep order
    seen = set()
    fonts = [f for f in fonts if not (f in seen or seen.add(f))]

    gray = img.convert("L")
    orig_masks = {}
    for g in glyphs:
        m = cut_original_glyph(gray, g["box"], thr)
        if m is not None:
            orig_masks[g["char"]] = m
    if not orig_masks:
        return []

    # the target ink height = median of the original glyph heights
    target_h = float(np.median([m.shape[0] for m in orig_masks.values()]))

    results = []
    for path in fonts:
        try:
            fidxs = [i for i, nm in face_names(path) if _face_is_interesting(nm)]
        except Exception:
            continue
        for idx in fidxs:
            # measure the face's ink height for a reference glyph at size 100
            ref_char = next(iter(orig_masks))
            try:
                f100 = ImageFont.truetype(path, 100, index=idx)
            except Exception:
                continue
            _, _, h100 = render_glyph_mask(ref_char, f100)
            if h100 <= 0:
                continue
            if sizes:
                cand_sizes = sizes
            else:
                cand_sizes = _size_candidates(target_h, h100)
            for size in cand_sizes:
                try:
                    f = ImageFont.truetype(path, size, index=idx)
                except Exception:
                    continue
                per = {}
                per_corr = {}
                for ch, om in orig_masks.items():
                    cm, _, _ = render_glyph_mask(ch, f)
                    m = best_match(om, cm, search)
                    per[ch] = m["iou"]
                    per_corr[ch] = m["corr"]
                iou = float(np.mean(list(per.values())))
                corr = float(np.mean(list(per_corr.values())))
                if iou <= 0:
                    continue
                nm = dict(face_names(path)).get(idx)
                # The score is the correlation: it measures the SHAPE of the
                # glyph, which is what identifies a typeface.  IoU is kept
                # as a tie-breaker and for reporting.
                score = 0.7 * corr + 0.3 * iou
                results.append({"font": path, "index": idx, "face": nm,
                                "size": size, "iou": iou, "corr": corr,
                                "score": score, "per_glyph": per,
                                "per_glyph_corr": per_corr})
    results.sort(key=lambda r: -r["score"])
    return results


def report(results, top=12):
    """Print a readable ranking table."""
    print(f"{'score':>6} {'corr':>6} {'IoU':>6}  {'size':>4}  "
          f"{'face':<30}  font")
    print("-" * 96)
    for r in results[:top]:
        fam, style = (r["face"] + ("", ""))[:2]
        print(f"{r.get('score', 0):>6.3f} {r.get('corr', 0):>6.3f} "
              f"{r['iou']:>6.3f}  {r['size']:>4}  "
              f"{(fam + ' ' + style)[:30]:<30}  {os.path.basename(r['font'])}")
        print("        per-glyph IoU: " + "  ".join(
            f"{k}={v:.3f}" for k, v in sorted(r["per_glyph"].items())))
