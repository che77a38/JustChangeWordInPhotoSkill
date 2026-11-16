#!/usr/bin/env python3
"""Ink rendering: make rendered glyphs look like ink printed on the photo.

THE MODEL (this is the whole trick)

A photographed printed character is a crisp glyph that has been convolved
with the camera's point-spread function, then composited onto paper with
the paper's own texture on top.  Nothing else.

    alpha = blur(feather(glyph), sigma)
    out   = paper * (1 - alpha) + ink * alpha
    out  += grain * alpha

Measured on the reference photo, one stroke of the original text has this
luminance profile (paper ~176, ink core ~44):

    178 175 175 175 176 179 188 191 189 | 181 169 164 163 153 138 118 94
    72 55 | 44 | 47 67 85 96 109 132 162 173 171 175

i.e. ONE smooth monotone ramp on each side of a solid core, about 9-10
pixels wide per side.  There is no second halo layer, no ragged edge, no
flying white.  Getting this wrong is what makes a paste look pasted.

WHAT NOT TO DO (each of these was tried and failed)

  * Spreading the mask and multiplying by noise -> a pale offset copy of
    the glyph (ghosting) and holes punched through the strokes (dashed).
  * Adding a separate soft "halo" layer -> a visible second, lighter copy
    of the character behind it.
  * Flying-white speckles inside the stroke -> the stroke breaks into dashes.
  * Dilating the glyph to make strokes fatter -> reads as a marker pen.

WHY A DARK CORE IS NOT REACHABLE BY BLUR ALONE

A gaussian blur of a thin stroke can never restore full opacity: the peak
alpha of a 7 px stroke blurred with sigma 2.4 is only about 0.55.  With
plain alpha compositing the core therefore stays grey, while real ink is
near black.  `contrast` adds a soft knee that pushes the covered part of
the ramp back towards 1.0 while leaving the outer ramp soft:

    a' = a + contrast * a * (1 - a)

Use contrast 0.4-0.8.  Above ~1.5 the knee becomes a hard step and the
edge stops looking photographic.
"""
import numpy as np
from PIL import Image, ImageFilter


def feather_outline(mask, radius=0.6):
    """Soften the vector edge by a fraction of a pixel (raster AA)."""
    if radius <= 0:
        return np.asarray(mask, np.float32)
    img = Image.fromarray((np.clip(mask, 0, 1) * 255).astype(np.uint8))
    img = img.filter(ImageFilter.GaussianBlur(radius))
    return np.asarray(img, np.float32) / 255.0


def blur_coverage(mask, sigma):
    """Gaussian blur of the glyph coverage - this is the camera PSF."""
    if sigma <= 0:
        return np.asarray(mask, np.float32)
    img = Image.fromarray((np.clip(mask, 0, 1) * 255).astype(np.uint8))
    img = img.filter(ImageFilter.GaussianBlur(sigma))
    return np.asarray(img, np.float32) / 255.0


def ink_alpha(mask, sigma=2.4, edge=0.6, gamma=0.92, contrast=0.0):
    """Coverage map of printed ink for a glyph mask (0..1 float)."""
    a = feather_outline(mask, edge)
    a = blur_coverage(a, sigma)
    a = np.clip(a, 0, 1)
    if contrast:
        a = np.clip(a + contrast * a * (1.0 - a), 0, 1)
    if gamma != 1.0:
        a = np.clip(a, 0, 1) ** gamma
    return np.clip(a, 0, 1)


def render_text(img, text, font, box, ink=(20, 20, 20), sigma=2.4,
                edge=0.6, gamma=0.92, contrast=0.0, grain=None,
                align="left", valign="center"):
    """Draw `text` onto `img` (a PIL Image) as printed ink.

    `box` is the target (x0, y0, x1, y1) the glyph ink should occupy.
    `align` is "left" or "center" horizontally; `valign` is "center" (the
    default), "top" or "bottom" vertically.
    """
    w, h = img.size
    m = Image.new("L", (w, h), 0)
    from PIL import ImageDraw
    from measure import ink_bbox
    tmp = Image.new("L", (6000, 2000), 0)
    ImageDraw.Draw(tmp).text((50, 50), text, font=font, fill=255)
    bb = ink_bbox(tmp)
    if bb is None:
        return img
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    x0, y0, x1, y1 = box
    if align == "center":
        tx = x0 + ((x1 - x0) - tw) // 2
    else:
        tx = x0
    if valign == "top":
        ty = y0
    elif valign == "bottom":
        ty = y1 - th
    else:
        ty = y0 + ((y1 - y0) - th) // 2
    # PIL's text() y is the top of the LAYOUT box (ascender), not the top of
    # the ink.  bb[1] is the ink top inside that layout box, so the ink lands
    # at (ty - bb[1] + bb[1]) = ty only if we offset by the layout origin.
    # Render once into the scratch image, then paste the ink block so the
    # ink lands exactly where we computed.
    glyph = tmp.crop(bb)
    m.paste(glyph, (int(tx), int(ty)))
    a = np.asarray(m, np.float32) / 255.0

    alpha = ink_alpha(a, sigma=sigma, edge=edge, gamma=gamma,
                      contrast=contrast)

    base = np.asarray(img, np.float32)
    col = np.array(ink, np.float32)[None, None, :]
    merged = base * (1 - alpha[:, :, None]) + col * alpha[:, :, None]
    if grain is not None:
        g = np.asarray(grain, np.float32)
        if g.ndim == 3:
            g = g.mean(axis=2)
        # the grain map is the high-frequency residual (h-2*half, w-2*half);
        # paste it back over the full frame
        hh, ww = merged.shape[:2]
        if g.shape[0] != hh or g.shape[1] != ww:
            gy = (hh - g.shape[0]) // 2
            gx = (ww - g.shape[1]) // 2
            full = np.zeros((hh, ww), np.float32)
            sy0, sy1 = max(0, gy), min(hh, gy + g.shape[0])
            sx0, sx1 = max(0, gx), min(ww, gx + g.shape[1])
            full[sy0:sy1, sx0:sx1] = g[sy0 - gy:sy1 - gy, sx0 - gx:sx1 - gx]
            g = full
        merged = merged + g[:, :, None] * alpha[:, :, None]
    return Image.fromarray(np.clip(merged, 0, 255).astype(np.uint8))


def solve_sigma(mask, paper, ink, reference_profile, sigma_range=None,
                edge=0.6, gamma=0.92, contrast=0.0):
    """Pick the blur sigma whose rendered profile best matches the photo.

    Renders the same glyph with each candidate sigma and compares the
    profile at the steepest stroke.  Returns (best_sigma, best_error).
    """
    from measure import profile_error
    if sigma_range is None:
        sigma_range = [round(1.0 + 0.2 * i, 2) for i in range(16)]
    best = None
    for s in sigma_range:
        a = ink_alpha(mask, sigma=s, edge=edge, gamma=gamma, contrast=contrast)
        ys, xs = np.nonzero(a > 0.5)
        if len(xs) == 0:
            continue
        x = int(xs[len(xs) // 2])
        col = a[:, x]
        prof = (paper * (1 - col) + ink * col).astype(int)
        err = profile_error(reference_profile, prof)
        if best is None or err < best[1]:
            best = (s, err)
    return best if best else (None, None)
