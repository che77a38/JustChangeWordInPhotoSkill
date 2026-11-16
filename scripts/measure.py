#!/usr/bin/env python3
"""Measurement helpers for photorealistic text replacement.

Everything here exists because of one hard lesson: when you edit text in a
photo, you must MEASURE the original and copy its numbers.  Guessing
parameters produces text that reads as pasted on.

The helpers answer the questions that actually decide whether a replacement
looks native:

  * which font face and weight is the original?      -> font_probe()
  * how big is the original text and where does it sit? -> text_geometry()
  * what does one stroke of the original look like?    -> stroke_profile()
  * how wide is the ink, how dark is the core?         -> ink_stats()
  * what does the local paper look like?               -> paper_level()
  * how soft is the camera?                            -> psf_sigma()

Only numpy and PIL are required.  scipy / OpenCV are NOT needed.
"""
import numpy as np
from PIL import Image, ImageFont

# --------------------------------------------------------------------------
# fonts
# --------------------------------------------------------------------------

# macOS ships Chinese faces as .ttc collections; face index selects the face.
# Probe them instead of assuming.
MAC_FONT_DIRS = [
    "/System/Library/AssetsV2/com_apple_MobileAsset_Font8",
    "/System/Library/Fonts",
    "/Library/Fonts",
]

FONT_CANDIDATES = {
    "kaiti": ["Kaiti.ttc", "STKaiti.ttf", "Kaiti SC.ttc"],
    "songti": ["Songti.ttc", "STSong.ttf", "Songti SC.ttc"],
    "heiti": ["Hiragino Sans GB.ttc", "STHeiti Medium.ttc", "STHeiti Light.ttc",
              "PingFang.ttc"],
    "pingfang": ["PingFang.ttc"],
    "yuanti": ["Yuanti.ttc", "STYuanti.ttf"],
    "fangsong": ["Fangsong.ttc", "STFangsong.ttf"],
}


def find_font_file(kind):
    """Locate a font file for `kind` on macOS.  Returns a path or None."""
    import glob
    import os
    names = FONT_CANDIDATES.get(kind, [])
    for d in MAC_FONT_DIRS:
        for n in names:
            hits = sorted(glob.glob(os.path.join(d, "**", n), recursive=True))
            if hits:
                return hits[0]
    return None


def face_names(path):
    """List the face names inside a .ttc/.otf collection."""
    names = []
    for i in range(0, 64):
        try:
            f = ImageFont.truetype(path, 20, index=i)
        except Exception:
            break
        try:
            names.append((i, f.getname()))
        except Exception:
            break
    return names


def stroke_width(mask, thr=None, dark_ink=True):
    """Median stroke width of a glyph region.

    Counts horizontal runs of ink per row and returns their median.
    `mask` may be a binary glyph (0/1 or 0/255, ink = high) or a grayscale
    photo region (ink = dark, `dark_ink=True` with `thr` a luminance
    threshold).
    """
    m = np.asarray(mask)
    if m.ndim == 3:
        m = m.mean(axis=2)
    if thr is None:
        thr = 0.5
    if dark_ink:
        b = m < thr
    else:
        if m.max() > 1:
            m = m / 255.0
        b = m > thr
    widths = []
    for row in b:
        c = 0
        for v in row:
            if v:
                c += 1
            elif c:
                widths.append(c)
                c = 0
        if c:
            widths.append(c)
    return float(np.median(widths)) if widths else 0.0


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------

def ink_bbox(mask, thr=None):
    """(x0, y0, x1, y1) of the ink in a mask, or None if empty."""
    m = np.asarray(mask)
    if m.max() > 1:
        m = m / 255.0
    if thr is None:
        thr = 0.5
    ys, xs = np.nonzero(m > thr)
    if len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def text_ink_size(text, font):
    """(w, h) of the ink box of `text` rendered with `font`."""
    from PIL import ImageDraw
    m = Image.new("L", (4000, 1200), 0)
    ImageDraw.Draw(m).text((100, 100), text, font=font, fill=255)
    bb = ink_bbox(m)
    return (bb[2] - bb[0], bb[3] - bb[1]) if bb else (0, 0)


def text_ink_width(text, font):
    """Width of the ink box of `text` rendered with `font`."""
    return text_ink_size(text, font)[0]


def render_text_mask(text, font, size_wh, offset=(0, 0)):
    """Rasterise `text` into a 0..1 float mask the size of `size_wh`.

    `offset` is the (x, y) where the glyph's ink box top-left lands.
    """
    from PIL import ImageDraw
    m = Image.new("L", size_wh, 0)
    ImageDraw.Draw(m).text(offset, text, font=font, fill=255)
    return np.asarray(m, np.float32) / 255.0


# --------------------------------------------------------------------------
# photo measurements
# --------------------------------------------------------------------------

def paper_level(img, box):
    """Local paper luminance: a high percentile of a mostly-blank region."""
    reg = np.asarray(img, np.float32)[box[1]:box[3], box[0]:box[2]]
    if reg.ndim == 3:
        reg = reg.mean(axis=2)
    if reg.size == 0:
        raise ValueError(f"empty region {box}")
    return float(np.percentile(reg, 88))


def background_level(img, box):
    """Local BACKGROUND luminance - the dominant colour of the region.

    For dark text on paper this is the paper (a high percentile); for light
    text on a coloured panel it is the panel colour (a low percentile).
    Use this when the ink may be lighter than the background.
    """
    reg = np.asarray(img, np.float32)[box[1]:box[3], box[0]:box[2]]
    if reg.ndim == 3:
        reg = reg.mean(axis=2)
    return float(np.percentile(reg, 12))


def ink_stats(img, box, paper=None, light=False):
    """Ink statistics of a text region.

    Returns a dict with the paper level, the core luminance (1st
    percentile), the median width of ink runs at several darkness levels and
    the ink coverage fraction.  These are the numbers you match.

    `light=True` is for light text on a dark or coloured background (white
    text on a green panel): the ink is BRIGHTER than the background.
    """
    reg = np.asarray(img, np.float32)[box[1]:box[3], box[0]:box[2]]
    if reg.ndim == 3:
        reg = reg.mean(axis=2)
    if paper is None:
        paper = (background_level(img, box) if light
                 else paper_level(img, box))
    if light:
        out = {"paper": float(paper),
               "core": float(np.percentile(reg, 99)),
               "coverage": float((reg > paper + 25).mean())}
        for frac in (0.60, 0.75, 0.85, 0.95):
            out[f"w{int(frac*100)}"] = stroke_width(reg, paper + (255 - paper) * frac,
                                                    dark_ink=False)
        return out
    out = {"paper": float(paper), "core": float(np.percentile(reg, 1)),
           "coverage": float((reg < paper - 25).mean())}
    for frac in (0.60, 0.75, 0.85, 0.95):
        out[f"w{int(frac*100)}"] = stroke_width(reg, paper * frac,
                                                dark_ink=True)
    return out


def stroke_profile(img, x, y0, y1, axis="v"):
    """Luminance profile along a line through a stroke.

    axis="v": a vertical cut at column x, returning rows y0..y1.
    axis="h": a horizontal cut at row y, returning columns x0..x1.
    """
    reg = np.asarray(img, np.float32)
    if reg.ndim == 3:
        reg = reg.mean(axis=2)
    if axis == "v":
        return reg[y0:y1, x].astype(int)
    return reg[y, x0:x1].astype(int)


def find_stroke(img, box, paper=None, axis="v"):
    """Find a clean, isolated stroke in a text box and return its profile.

    Scans for the row/column whose cut crosses the ink most sharply (a
    near-horizontal or near-vertical stroke).  Returns (index, profile).
    """
    reg = np.asarray(img, np.float32)
    if reg.ndim == 3:
        reg = reg.mean(axis=2)
    if paper is None:
        paper = paper_level(img, box)
    x0, y0, x1, y1 = box
    best = None
    if axis == "v":
        for x in range(x0, x1):
            col = reg[y0:y1, x]
            ink = col < paper * 0.75
            if ink.sum() < 6:
                continue
            # score: how sharply the profile falls through the paper level
            d = np.abs(np.diff(col.astype(float)))
            s = d.sum()
            if best is None or s > best[0]:
                best = (s, x, col.astype(int))
        if best:
            return best[1], best[2]
    else:
        for y in range(y0, y1):
            row = reg[y, x0:x1]
            ink = row < paper * 0.75
            if ink.sum() < 6:
                continue
            d = np.abs(np.diff(row.astype(float)))
            s = d.sum()
            if best is None or s > best[0]:
                best = (s, y, row.astype(int))
        if best:
            return best[1], best[2]
    return None, None


def psf_sigma(img, box, paper=None):
    """Estimate the camera's blur sigma from the ink edge ramp.

    A blurred edge with a 10%-90% ramp of width w corresponds to
    sigma ~= w / 2.56.  Scans every column of the box for the cleanest
    stroke and returns the median of the per-cut estimates.
    """
    paper = paper_level(img, box) if paper is None else paper
    reg = np.asarray(img, np.float32)
    if reg.ndim == 3:
        reg = reg.mean(axis=2)
    x0, y0, x1, y1 = box
    sigmas = []
    for x in range(x0, x1, 2):
        col = reg[y0:y1, x]
        if (col < paper * 0.75).sum() < 4:
            continue
        s = _sigma_from_profile(col, paper)
        if s is not None:
            sigmas.append(s)
    if not sigmas:
        return None
    sigmas.sort()
    return float(sigmas[len(sigmas) // 2])


def _sigma_from_profile(p, paper):
    """sigma of a single edge profile (a luminance array)."""
    p = np.asarray(p, float)
    ink = p < paper * 0.75
    if ink.sum() < 3:
        return None
    i0, i1 = int(np.nonzero(ink)[0].min()), int(np.nonzero(ink)[0].max())
    core = p[i0:i1 + 1].min()
    if core >= paper * 0.9:
        return None
    # 10% and 90% levels between paper and core
    l10 = paper - 0.9 * (paper - core)
    l90 = paper - 0.1 * (paper - core)
    widths = []
    # left edge
    seg = p[i0 - 14:i0 + 1][::-1]
    idx = np.nonzero((seg <= l90) & (seg >= l10))[0]
    if len(idx) > 1:
        widths.append(idx.max() - idx.min())
    # right edge
    seg = p[i1:i1 + 15]
    idx = np.nonzero((seg <= l90) & (seg >= l10))[0]
    if len(idx) > 1:
        widths.append(idx.max() - idx.min())
    if not widths:
        return None
    return float(max(widths)) / 2.56


def profile_error(a, b):
    """Mean absolute difference between two luminance profiles, aligned on
    their darkest point.  Lower is better; used to pick the blur sigma."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    ai = int(np.argmin(a))
    bi = int(np.argmin(b))
    a = a[ai - 11: ai + 12]
    b = b[bi - 11: bi + 12]
    n = min(len(a), len(b))
    return float(np.abs(a[:n] - b[:n]).mean())


# --------------------------------------------------------------------------
# background reconstruction
# --------------------------------------------------------------------------

def vertical_median(img, half=110, step=5, pct=70, texture=True):
    """Estimate the paper background with a per-column vertical statistic.

    Text sits in short horizontal bands, so a tall vertical window sees the
    paper on both sides of every glyph.  Using the `pct` percentile (rather
    than the median) removes ink robustly.

    `half` is the half-height of the sampling window in pixels; `step` is
    how many rows to advance per sample.  With `texture` the local paper
    grain is added back so the result is not a flat, banded plate.

    Returns a float array.
    """
    a = np.asarray(img, np.float32)
    h, w = a.shape[:2]
    out = np.empty_like(a)
    for x in range(w):
        col = a[:, x]
        vals = []
        for y in range(0, h, step):
            s = col[max(0, y - half): min(h, y + half + 1)]
            if len(s):
                vals.append(np.percentile(s, pct))
        v = float(np.median(vals)) if vals else 0.0
        out[:, x] = v
    # smooth vertically so the result is a clean gradient
    k = 51
    pad = np.pad(out, ((k // 2, k // 2), (0, 0)) + ((0, 0),) * (out.ndim - 2),
                  mode="edge")
    cs = np.cumsum(pad, axis=0)
    sm = (cs[k:] - cs[:-k]) / k
    if texture:
        # add back the paper's own fine grain, taken from the whole frame
        g = highfreq(a, half=3)
        if g.ndim == 2:
            g = g[:, :, None]
        hh, ww = sm.shape[:2]
        full = np.zeros((hh, ww, sm.shape[2]), np.float32)
        gy, gx = (hh - g.shape[0]) // 2, (ww - g.shape[1]) // 2
        full[gy:gy + g.shape[0], gx:gx + g.shape[1]] = g
        sm = sm + full
    return sm[:h]


def highfreq(img, half=3):
    """High-frequency residual of an image: the paper grain."""
    from numpy.lib.stride_tricks import sliding_window_view
    a = np.asarray(img, np.float32)
    if a.ndim == 3:
        a = a.mean(axis=2)
    w = sliding_window_view(a, (2 * half + 1, 2 * half + 1))
    blur = w.mean(axis=(2, 3))
    return a[half:-half, half:-half] - blur


def match_level(dst, src):
    """Shift `dst` so its mean level equals `src`'s."""
    return dst + (src - dst.mean())


def feather_rect(h, w, feather=26):
    """A 2-D rectangular feather mask: 1 in the middle, ramping to 0 at the
    edges.  Used to blend a reconstructed background into the photo."""
    m = np.ones((h, w), np.float32)
    f = min(feather, h // 2, w // 2)
    if f <= 0:
        return m
    ramp = np.linspace(0, 1, f, dtype=np.float32)
    m[:f, :] *= ramp[:, None]
    m[-f:, :] *= ramp[::-1][:, None]
    m[:, :f] *= ramp[None, :]
    m[:, -f:] *= ramp[::-1][None, :]
    return m


def ink_mask(img, box, paper=None, thresh=0.95, min_run=3, grow=2,
             light=False, dark_thresh=None):
    """Detect the ink pixels inside `box`.

    Returns a boolean mask of the pixels that belong to the text.  Uses a
    dark-pixel test against the local paper level plus a run-length filter
    so isolated noise is not included, then grows the mask by `grow` pixels
    so the soft blur halo of the strokes is covered too - otherwise the old
    text leaves a ghost.

    `light=True` inverts the test for LIGHT text on a dark or coloured
    background (e.g. white text on a green panel): the ink is brighter than
    the background, so "ink" is `reg > paper + (255-paper)*thresh`.

    `dark_thresh` is an ABSOLUTE luminance threshold.  Use it when the
    region contains other dark features (a watermark, a seal, a rule
    line) that must NOT be treated as text: the paper-relative test would
    happily eat them, and the inpaint would then replace a real background
    feature with flat paper.  Measured on the reference card the printed
    ink bottoms out at 0 and the watermark at 113, so `--dark-thresh 115`
    cleanly separates the two.

    A cheap max-filter (dilation) is used instead of scipy.ndimage, which
    is not guaranteed to be installed.
    """
    a = np.asarray(img, np.float32)
    if a.ndim == 3:
        a = a.mean(axis=2)
    x0, y0, x1, y1 = box
    reg = a[y0:y1, x0:x1]
    if light:
        if paper is None:
            paper = background_level(img, box)
        m = reg > paper + (255.0 - paper) * thresh
    else:
        if dark_thresh is not None:
            m = reg < dark_thresh
        else:
            if paper is None:
                paper = paper_level(img, box)
            m = reg < paper * thresh
    # keep only runs of at least min_run dark pixels (drops noise)
    out = np.zeros_like(m)
    for r in range(m.shape[0]):
        row = m[r]
        i = 0
        while i < len(row):
            if row[i]:
                j = i
                while j < len(row) and row[j]:
                    j += 1
                if (j - i) >= min_run:
                    out[r, i:j] = True
                i = j
            else:
                i += 1
    # grow the mask to swallow the blur halo
    for _ in range(max(0, grow)):
        acc = out.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                acc |= np.roll(np.roll(out, dy, axis=0), dx, axis=1)
        out = acc
    return out


def inpaint(img, box, ink_mask_arr, radius=12, per_channel=True):
    """Fill the ink pixels of `box` by interpolating from the paper around
    them.

    The fill is a multi-pass diffusion that runs until every ink pixel has
    a value (the pass count grows with the size of the strokes), so a
    20-pixel-wide glyph is filled from its real paper surroundings instead
    of leaving a dark smudge.

    This keeps every background feature that is not ink - a watermark, a
    seal, a fold line, a colour band - exactly where it was, which is what
    makes the erased area read as real paper.

    `per_channel=True` (the default) diffuses each RGB channel separately.
    This is NOT optional on coloured paper: a luminance-only fill copied
    into all three channels turns a cool blue paper (155,167,176) into
    neutral grey (165,165,165), which reads as a beige ghost of the old
    strokes.  Set it to False only for a greyscale image.
    """
    a = np.asarray(img, np.float32).copy()
    x0, y0, x1, y1 = box
    h, w = y1 - y0, x1 - x0
    sub = a[y0:y1, x0:x1]
    m = np.asarray(ink_mask_arr, bool)
    if m.shape != (h, w):
        raise ValueError(f"ink_mask shape {m.shape} != box shape {(h, w)}")
    if sub.ndim == 2:
        sub = sub[:, :, None]
    filled = sub.copy()
    # `known` is per-CHANNEL: a channel is known where its pixel is not
    # ink.  (With a single channel it degenerates to the old behaviour.)
    known = (~m)[:, :, None] & np.ones((1, 1, filled.shape[2]), bool)
    # number of passes needed: enough for the widest stroke to be crossed
    passes = int(min(h, w)) // 2 + 4
    for _ in range(passes):
        if known.all():
            break
        acc = np.zeros_like(filled)
        cnt = np.zeros_like(filled)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                sh = np.roll(np.roll(filled, dy, axis=0), dx, axis=1)
                km = np.roll(np.roll(known, dy, axis=0), dx, axis=1)
                # np.roll wraps; kill the wrapped border
                if dy == 1:
                    km[0, :, :] = False
                elif dy == -1:
                    km[-1, :, :] = False
                if dx == 1:
                    km[:, 0, :] = False
                elif dx == -1:
                    km[:, -1, :] = False
                acc += sh * km
                cnt += km
        avg = acc / np.maximum(cnt, 1e-6)
        take = (~known) & (cnt > 0)
        filled = np.where(take, avg, filled)
        known = known | take
    # smooth the filled area so the diffusion pattern disappears
    blurred = np.empty_like(filled)
    for ch in range(filled.shape[2]):
        b = filled[:, :, ch]
        k = 9
        pad = np.pad(b, k // 2, mode="edge")
        cs = np.cumsum(np.cumsum(pad, axis=0), axis=1)
        cs = np.pad(cs, ((1, 0), (1, 0)))
        win = (cs[k:, k:] - cs[:-k, k:] - cs[k:, :-k] + cs[:-k, :-k]) / (k * k)
        blurred[:, :, ch] = win
    filled = np.where(m[:, :, None], blurred, filled)
    a[y0:y1, x0:x1] = filled
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def erase_region(img, box, background, feather=26, grain=None):
    """Replace the pixels inside `box` with the reconstructed background.

    The replacement is feathered at the edges so no seam is visible, and the
    real paper grain of the photo is added back on top.
    """
    a = np.asarray(img, np.float32).copy()
    x0, y0, x1, y1 = box
    bg = np.asarray(background, np.float32)
    h, w = y1 - y0, x1 - x0
    if h <= 0 or w <= 0:
        return img
    m = feather_rect(h, w, feather)[..., None]
    patch = a[y0:y1, x0:x1]
    a[y0:y1, x0:x1] = patch * (1 - m) + bg[y0:y1, x0:x1] * m
    if grain is not None:
        g = np.asarray(grain, np.float32)
        if g.ndim == 2:
            g = g[:, :, None]
        a[y0:y1, x0:x1] += g * m
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


# --------------------------------------------------------------------------
# geometry: where exactly is the ink?
# --------------------------------------------------------------------------

def ink_extent(img, box, thr=None, min_px=3, dark_thresh=None, light=False):
    """The tight ink bbox of the text inside `box`.

    Returns (x0, y0, x1, y1) in absolute image coordinates, or None.

    This is the box the erase step MUST use.  A row-shaped region is
    dangerous: it also covers the background gradient and any watermark
    below the text, and the inpaint will then replace those real
    background features with flat paper.

    `thr` is the luminance threshold.  When `dark_thresh` is given it is
    used as an absolute threshold (useful to separate printed ink from a
    slightly lighter watermark).  `min_px` is the minimum number of ink
    pixels a row (or column) needs to count as part of the text, which
    stops a single stray pixel from stretching the box.
    """
    a = np.asarray(img, np.float32)
    if a.ndim == 3:
        a = a.mean(axis=2)
    x0, y0, x1, y1 = box
    reg = a[y0:y1, x0:x1]
    if reg.size == 0:
        return None
    if light:
        paper = background_level(img, box)
        m = reg > paper + (255.0 - paper) * 0.6
    elif dark_thresh is not None:
        m = reg < dark_thresh
    else:
        if thr is None:
            thr = paper_level(img, box) * 0.75
        m = reg < thr
    rows = np.nonzero(m.sum(axis=1) >= min_px)[0]
    cols = np.nonzero(m.sum(axis=0) >= min_px)[0]
    if len(rows) == 0 or len(cols) == 0:
        return None
    return (x0 + int(cols.min()), y0 + int(rows.min()),
            x0 + int(cols.max()) + 1, y0 + int(rows.max()) + 1)


def column_runs(img, box, thr=None, min_gap=2, dark_thresh=None, light=False):
    """Group the ink columns of a text row into per-character runs.

    Returns a list of (x_start, x_end) pairs, absolute coordinates.

    A gap-tolerant column scan is the reliable way to find where each
    character starts and ends.  Use a LOWER threshold than the obvious
    one: at threshold 130 the last 「源」 of the reference card was cut at
    x=2749 when it really reaches x=2805, which left 56 px of the old
    glyph in the picture (a visible dark stub).
    """
    a = np.asarray(img, np.float32)
    if a.ndim == 3:
        a = a.mean(axis=2)
    x0, y0, x1, y1 = box
    reg = a[y0:y1, x0:x1]
    if reg.size == 0:
        return []
    if light:
        paper = background_level(img, box)
        col = (reg > paper + (255.0 - paper) * 0.6).sum(axis=0)
    elif dark_thresh is not None:
        col = (reg < dark_thresh).sum(axis=0)
    else:
        if thr is None:
            thr = paper_level(img, box) * 0.75
        col = (reg < thr).sum(axis=0)
    has = col > 0
    runs = []
    i = 0
    while i < len(has):
        if has[i]:
            j = i
            gap = 0
            while j < len(has):
                if has[j]:
                    gap = 0
                    j += 1
                else:
                    gap += 1
                    if gap > min_gap:
                        break
                    j += 1
            runs.append((x0 + i, x0 + j - gap - 1))
            i = j
        else:
            i += 1
    return runs


def row_extent(img, box, thr=None, min_px=3, dark_thresh=None, light=False):
    """The tight vertical ink extent (top, bottom) of the text in `box`."""
    e = ink_extent(img, box, thr=thr, min_px=min_px,
                   dark_thresh=dark_thresh, light=light)
    if e is None:
        return None
    return (e[1], e[3])
