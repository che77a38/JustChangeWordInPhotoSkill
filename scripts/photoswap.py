#!/usr/bin/env python3
"""photoswap-text - replace text in a photo so it looks printed, not pasted.

Workflow
--------
1.  probe    - measure the original: font face, size, position, ink colour,
               blur sigma.  Prints a JSON plan.
2.  edit     - apply the plan: rebuild the background, erase the old text,
               render the new text as ink.
3.  compare  - render original vs edited side by side for visual checking.

Example
-------
    python3 photoswap.py probe   card.jpg  --region 1868,1508,2826,1688 \\
                                --sample "数字金融学院"
    python3 photoswap.py edit    card.jpg  --plan plan.json -o out.jpg
    python3 photoswap.py compare card.jpg  out.jpg --crop 1868,1508,2826,1688
"""
import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import measure as M  # noqa: E402
import ink as INK  # noqa: E402
import fontid as FID  # noqa: E402


# --------------------------------------------------------------------------
def load(path):
    im = Image.open(path)
    if im.mode != "RGB":
        im = im.convert("RGB")
    return im


def region_box(s):
    box = tuple(int(v) for v in s.split(","))
    if len(box) != 4:
        raise ValueError(
            f"region must be 'x0,y0,x1,y1', got {s!r}")
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        raise ValueError(
            f"region must have x1 > x0 and y1 > y0, got {s!r}")
    return box


def parse_glyphs(items):
    """Parse "char:x0,y0,x1,y1" specs into glyph dicts."""
    out = []
    for it in items:
        if ":" not in it:
            raise ValueError(
                f"glyph spec must be 'char:x0,y0,x1,y1', got {it!r}")
        ch, box = it.split(":", 1)
        out.append({"char": ch, "box": region_box(box)})
    return out


# --------------------------------------------------------------------------
def cmd_fontid(args):
    """Identify the typeface used by a set of glyphs in an image."""
    im = load(args.image)
    glyphs = parse_glyphs(args.glyph)
    fonts = None
    if args.font:
        fonts = list(args.font)
    sizes = None
    if args.size:
        sizes = [int(v) for v in args.size.split(",")]

    # --- make sure the open-source families are on disk ------------------
    # The image may well have been made with Noto / Source Han, which are
    # NOT installed by default on macOS or Windows.  Without the real font
    # file the matcher can only answer with the nearest SYSTEM face, and
    # that answer is wrong in a way that is hard to see.
    if not args.no_download:
        have = {os.path.basename(f) for f in
                (fonts if fonts else FID.find_local_fonts(
                    args.project_dir or ()) + FID.find_system_fonts())}
        missing = [k for k, v in FID.DOWNLOADABLE_FAMILIES.items()
                   if v[1] not in have]
        if missing:
            print(f"note: {len(missing)} open-source CJK family/families are "
                  f"not on this machine: {', '.join(missing)}")
            print("      The image may have been made with one of them.  "
                  "Fetching them for a fair comparison ...")
            for k in missing:
                url, fname, _faces = FID.DOWNLOADABLE_FAMILIES[k]
                got = FID.fetch_font(url, fname,
                                     dest_dir=args.font_dir or None)
                if got:
                    print(f"      fetched {fname}")
                    if fonts is None:
                        fonts = []
                    fonts.append(got)

    res = FID.identify(im, glyphs, fonts=fonts, sizes=sizes,
                        thr=args.thresh, search=args.search,
                        project_dirs=args.project_dir or ())
    if args.json:
        out = []
        for r in res[:args.top]:
            out.append({"score": round(r.get("score", 0), 4),
                        "corr": round(r.get("corr", 0), 4),
                        "iou": round(r["iou"], 4),
                        "size": r["size"], "face": list(r["face"]),
                        "font": r["font"], "index": r["index"],
                        "per_glyph": {k: round(v, 4)
                                      for k, v in r["per_glyph"].items()}})
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        FID.report(res, top=args.top)
    if res:
        best = res[0]
        print()
        print("BEST:")
        fam, style = (best["face"] + ("", ""))[:2]
        print(f"  font  {best['font']}")
        print(f"  face  index {best['index']}  ({fam} {style})")
        print(f"  size  {best['size']}")
        print(f"  score {best.get('score', 0):.3f}  "
              f"corr {best.get('corr', 0):.3f}  IoU {best['iou']:.3f}")


# --------------------------------------------------------------------------
def cmd_geometry(args):
    """Measure where the ink really is, so the erase step can be safe.

    Prints the tight ink bbox of the region and the per-character column
    runs.  USE THIS BEFORE ERASING: a row-shaped erase box also covers the
    background gradient and any watermark below the text, and the inpaint
    will then replace those real background features with flat paper.
    """
    im = load(args.image)
    box = region_box(args.region)
    light = args.light_ink
    dark = args.dark_thresh or None
    e = M.ink_extent(im, box, thr=args.thr, min_px=args.min_px,
                     dark_thresh=dark, light=light)
    runs = M.column_runs(im, box, thr=args.thr, dark_thresh=dark,
                          light=light)
    paper = (M.background_level(im, box) if light
             else M.paper_level(im, box))
    out = {"region": list(box), "paper": paper}
    out["ink_bbox"] = list(e) if e else None
    out["column_runs"] = [list(r) for r in runs]
    if e:
        out["ink_size"] = [e[2] - e[0], e[3] - e[1]]
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if e:
        print()
        print(f"ERASE BOX (hug the ink): {e[0]},{e[1]},{e[2]},{e[3]}")
        print("Character column groups: " + "  ".join(
            f"({r[0]}-{r[1]})" for r in runs))


# --------------------------------------------------------------------------
def cmd_probe(args):
    im = load(args.image)
    a = np.asarray(im, np.float32)
    box = region_box(args.region)
    paper = M.paper_level(im, box)
    stats = M.ink_stats(im, box, paper)
    sigma = M.psf_sigma(im, box, paper)

    plan = {
        "image": os.path.abspath(args.image),
        "size": list(im.size),
        "region": list(box),
        "paper": stats["paper"],
        "ink_core": stats["core"],
        "stroke_widths": {k: stats[k] for k in
                          ("w60", "w75", "w85", "w95")},
        "coverage": stats["coverage"],
        "psf_sigma": sigma,
    }

    if args.sample:
        # identify the face: render the sample text in every candidate face
        # and compare the ink profile / stroke width with the photo.
        best = []
        for kind in M.FONT_CANDIDATES:
            path = M.find_font_file(kind)
            if not path:
                continue
            for idx, name in M.face_names(path):
                if "Bold" not in name[1] and "Black" not in name[1] \
                        and "Regular" not in name[1] and "Medium" not in name[1]:
                    continue
                try:
                    f = ImageFont.truetype(path, args.size, index=idx)
                except Exception:
                    continue
                w, h = M.text_ink_size(args.sample, f)
                best.append({"kind": kind, "path": path, "index": idx,
                             "face": name[1], "ink_w": w, "ink_h": h})
        # keep faces whose proportions fit the photo's text box
        bh = box[3] - box[1]
        cands = [b for b in best if abs(b["ink_h"] - bh) <= bh * 0.25]
        plan["faces"] = cands or best
    print(json.dumps(plan, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------
def cmd_edit(args):
    plan = json.load(open(args.plan)) if args.plan else {}
    im = load(args.image)
    a = np.asarray(im, np.float32)
    box = region_box(args.region) if args.region else tuple(plan["region"])
    light = args.light_ink
    paper = plan.get("paper")
    if paper is None:
        paper = (M.background_level(im, box) if light
                 else M.paper_level(im, box))
    # On a flat UI screenshot the paper level is pure white (255) and the
    # "grain" residual is just the anti-aliasing of the ORIGINAL text.
    # Adding it on top of the new text makes the glyphs look doubled and
    # grey, so it has to be switched off there.
    flat_screen = paper >= 250.0

    # ------------------------------------------------------------------
    # FIT: the new text has to fit the slot the old text occupied.
    # If the new string is wider than the old ink, either shrink the
    # size until it fits, or refuse and tell the caller.  Rendering a
    # longer string into a narrower slot silently overlaps the old ink
    # that was never erased - that is what makes an edit look broken.
    # ------------------------------------------------------------------
    size = args.size
    font = ImageFont.truetype(args.font, size, index=args.face)
    new_w = M.text_ink_width(args.text, font)
    old_w = None
    if args.fit != "off":
        ext = M.ink_extent(im, box, dark_thresh=args.dark_thresh or None,
                           light=light)
        if ext:
            old_w = ext[2] - ext[0]
    if old_w and args.fit == "shrink" and new_w > old_w:
        # binary-search the largest size whose ink still fits
        lo, hi = 8, size
        best = None
        while lo <= hi:
            mid = (lo + hi) // 2
            f = ImageFont.truetype(args.font, mid, index=args.face)
            if M.text_ink_width(args.text, f) <= old_w:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if best:
            size = best
            font = ImageFont.truetype(args.font, size, index=args.face)
            new_w = M.text_ink_width(args.text, font)
            print(f"fit: shrunk size {args.size} -> {size} "
                  f"(ink {new_w}px fits the {old_w}px slot)")
    if old_w and new_w > old_w:
        print(f"WARNING: new text ink is {new_w}px wide but the old slot is "
              f"only {old_w}px wide.  The text will overlap the old ink.  "
              f"Widen --region / use --fit shrink, or shorten the text.")
    if old_w:
        print(f"fit: old ink width {old_w}px, new ink width {new_w}px")

    grain_full = M.highfreq(im, half=3)
    # A flat UI screenshot has no paper grain - the "high frequency residual"
    # there is just the anti-aliasing of the ORIGINAL text, and adding it on
    # top of the new text makes the glyphs look doubled, grey and patchy.
    # "auto" turns the grain off when the residual is dominated by text
    # edges rather than paper texture (a photo's residual std is ~5, a
    # screenshot's is ~15 because the glyph AA lands in it).
    if args.grain == "off":
        grain_full = None
    elif args.grain == "auto":
        # A flat UI screenshot has no paper grain: the high-frequency
        # residual is the anti-aliasing of the ORIGINAL text (std ~15.7 on
        # the reference screenshot vs ~5 on a photograph).  Adding it on
        # top of the new text makes the glyphs look doubled and grey.
        hf_std = float(np.std(grain_full))
        if flat_screen or hf_std > 9.0 or paper > 250 or paper < 20:
            grain_full = None

    if args.erase == "inpaint":
        # --- erase only the ink; every other background feature stays -----
        # --dark-thresh 0 means "off" (use the paper-relative test).  It has
        # to be translated to None here: ink_mask() treats a non-None
        # dark_thresh as an ABSOLUTE threshold, so passing 0 would make the
        # test "reg < 0" - nothing is detected, nothing is erased, and the
        # old text survives to collide with the new text.
        dark_thresh = args.dark_thresh or None
        m = M.ink_mask(im, box, paper, thresh=args.ink_thresh,
                       min_run=args.min_run, grow=args.grow, light=light,
                       dark_thresh=dark_thresh)
        im2 = M.inpaint(im, box, m, per_channel=not args.no_per_channel)
    else:
        # --- rebuild the paper background without the old text -------------
        bg = M.vertical_median(a, half=args.bg_half, step=5, pct=args.bg_pct)
        grain = np.zeros((box[3] - box[1], box[2] - box[0]), np.float32)
        im2 = M.erase_region(im, box, bg, feather=args.feather, grain=grain)

    # --- render the new text -----------------------------------------
    target = (box[0], box[1], box[2], box[3])
    if args.align_x:
        target = (args.align_x, box[1], args.align_x + (box[2] - box[0]),
                  box[3])
    out = INK.render_text(im2, args.text, font, target,
                          ink=tuple(args.ink), sigma=args.sigma,
                          edge=args.edge, gamma=args.gamma,
                          contrast=args.contrast,
                          grain=grain_full, align=args.align,
                          valign=args.valign)

    # --- re-lay the NEIGHBOURING elements of the same row --------------
    # When the new value is longer, the elements after it (a "|" separator,
    # a second value) have to move, otherwise they either collide with the
    # new text or sit with the wrong gap.  --extra takes
    #   "text@x,size"        - draw this text at this x with this size
    #   "text@x,size@gap"    - the gap to keep before it
    # The first extra is placed gap px after the ink of the new value; all
    # following ones are placed gap px after the previous element.
    if args.extra:
        ink_right = target[0] + new_w - 1
        cursor = ink_right
        for spec in args.extra:
            # format:  "text@x,size"          absolute x
            #          "text@-gap,size"       gap px after the previous element
            #          "text@x,size@gap"      absolute x, then leave `gap` px
            body, _, rest = spec.partition("@")
            x_s, _, size_s = rest.partition(",")
            gap = 0
            if "@" in rest:
                _, _, gap_s = rest.partition("@")
                gap = int(gap_s)
            x = int(x_s)
            esize = int(size_s) if size_s else size
            if x < 0:
                x = cursor + (-x)
            efont = ImageFont.truetype(args.font, esize, index=args.face)
            out = INK.render_text(out, body, efont,
                                  (x, target[1], x + (box[2] - box[0]), box[3]),
                                  ink=tuple(args.ink), sigma=args.sigma,
                                  edge=args.edge, gamma=args.gamma,
                                  contrast=args.contrast, grain=None,
                                  align=args.align, valign=args.valign)
            ew = M.text_ink_width(body, efont)
            cursor = x + ew - 1
            if gap:
                cursor += gap
            print(f"extra: {body!r} at x={x} size={esize} ink={ew}px")

    out.save(args.output, quality=args.quality)
    print("wrote", args.output, out.size)


# --------------------------------------------------------------------------
def cmd_compare(args):
    a = load(args.image)
    b = load(args.output)
    box = region_box(args.crop)
    ca = a.crop(box)
    cb = b.crop(box)
    w, h = ca.size
    scale = args.width / w
    ch = int(h * scale)
    ca = ca.resize((args.width, ch), Image.LANCZOS)
    cb = cb.resize((args.width, ch), Image.LANCZOS)
    gap = 20
    canvas = Image.new("RGB", (args.width, ch * 2 + gap), (255, 255, 255))
    canvas.paste(ca, (0, 0))
    canvas.paste(cb, (0, ch + gap))
    out = args.output.rsplit(".", 1)[0] + "_compare.png"
    canvas.save(out)
    print("wrote", out)


# --------------------------------------------------------------------------
def cmd_verify(args):
    """Compare the ink statistics of the original and the edited region.

    Prints a table of the numbers that decide whether the replacement looks
    native: paper level, ink core darkness, stroke width at several levels
    and ink coverage.
    """
    a = load(args.image)
    b = load(args.output)
    box = region_box(args.region)
    sa = M.ink_stats(a, box, light=args.light_ink)
    sb = M.ink_stats(b, box, light=args.light_ink)
    keys = ["paper", "core", "w60", "w75", "w85", "w95", "coverage"]
    print(f"{'metric':<10}{'original':>12}{'edited':>12}")
    for k in keys:
        va, vb = sa.get(k), sb.get(k)
        if va is None or vb is None:
            continue
        flag = ""
        if k.startswith("w") and k[1:].isdigit():
            if abs(va - vb) > 3:
                flag = "  <-- differs"
        elif k in ("core", "paper") and abs(va - vb) > 25:
            flag = "  <-- differs"
        print(f"{k:<10}{va:>12.2f}{vb:>12.2f}{flag}")


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(prog="photoswap-text")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe")
    p.add_argument("image")
    p.add_argument("--region", required=True,
                   help="x0,y0,x1,y1 of the text block in the photo")
    p.add_argument("--sample", help="the ORIGINAL text, for face matching")
    p.add_argument("--size", type=int, default=160, help="trial font size")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("edit")
    p.add_argument("image")
    p.add_argument("--plan")
    p.add_argument("--region")
    p.add_argument("--text", required=True)
    p.add_argument("--font", required=True)
    p.add_argument("--face", type=int, default=0)
    p.add_argument("--size", type=int, default=160)
    p.add_argument("--align", default="left", choices=["left", "center"])
    p.add_argument("--valign", default="center",
                   choices=["center", "top", "bottom"])
    p.add_argument("--align-x", type=int, default=0)
    p.add_argument("--ink", type=int, nargs=3, default=[20, 20, 20])
    p.add_argument("--sigma", type=float, default=2.4)
    p.add_argument("--edge", type=float, default=0.6,
                   help="raster anti-alias radius of the glyph edge, in px")
    p.add_argument("--gamma", type=float, default=0.92)
    p.add_argument("--contrast", type=float, default=0.0)
    p.add_argument("--grain", default="auto", choices=["auto", "on", "off"],
                   help="add the photo's paper texture on top of the ink; "
                        "off for flat UI screenshots")
    p.add_argument("--light-ink", action="store_true",
                   help="the text is LIGHTER than the background "
                        "(white text on a coloured panel)")
    p.add_argument("--feather", type=int, default=26)
    p.add_argument("--bg-half", type=int, default=110)
    p.add_argument("--bg-pct", type=int, default=70,
                   help="percentile of the vertical window used as paper level")
    p.add_argument("--erase", default="inpaint", choices=["bg", "inpaint"],
                   help="bg = rebuild the paper background; "
                        "inpaint = fill only the ink pixels (keeps a "
                        "watermark/seal in place)  [default: inpaint]")
    p.add_argument("--ink-thresh", type=float, default=0.95,
                   help="pixels darker than paper*this are treated as ink")
    p.add_argument("--dark-thresh", type=int, default=0,
                   help="ABSOLUTE luminance threshold for ink detection "
                        "(0 = off).  Use it when the region contains other "
                        "dark features - a watermark, a seal, a rule line - "
                        "that must not be treated as text: the paper-"
                        "relative test would eat them and the inpaint would "
                        "replace a real background feature with flat paper")
    p.add_argument("--extra", action="append", default=[],
                   help="re-lay a neighbouring element of the same row, e.g. "
                        "'|@530,46' or '普通全日制@583,46'.  A negative x is "
                        "relative to the previous element (-54 = 54px after "
                        "it).  Repeat the flag for several elements.")
    p.add_argument("--fit", choices=["off", "warn", "shrink"], default="warn",
                   help="make the new text fit the slot the old text "
                        "occupied: warn (report both widths) or shrink "
                        "(reduce the size until the new ink fits).  A new "
                        "string that is WIDER than the old ink overlaps "
                        "the old glyphs that were never erased")
    p.add_argument("--min-run", type=int, default=3,
                   help="minimum run length of dark pixels to count as ink")
    p.add_argument("--grow", type=int, default=2,
                   help="grow the ink mask by N px to cover the blur halo")
    p.add_argument("--no-per-channel", action="store_true",
                   help="diffuse the fill on luminance only.  NEVER do this "
                        "on coloured paper: it turns cool blue paper "
                        "(155,167,176) into neutral grey (165,165,165) and "
                        "leaves a beige ghost of the old strokes")
    p.add_argument("--quality", type=int, default=97)
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_edit)

    p = sub.add_parser("compare")
    p.add_argument("image")
    p.add_argument("output")
    p.add_argument("--crop", required=True)
    p.add_argument("--width", type=int, default=1540)
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("fontid")
    p.add_argument("image")
    p.add_argument("--glyph", action="append", required=True,
                   help="char:x0,y0,x1,y1  (repeatable; box must hug the "
                        "glyph's ink bbox)")
    p.add_argument("--font", action="append",
                   help="candidate font file (repeatable).  Default: the "
                        "project's local CJK fonts + the macOS system faces")
    p.add_argument("--project-dir", action="append",
                   help="extra directory to look for local font files")
    p.add_argument("--size", help="explicit point sizes, comma separated")
    p.add_argument("--thresh", type=int, default=200,
                   help="luminance below which a pixel counts as ink")
    p.add_argument("--search", type=int, default=4,
                   help="translation search radius, in px")
    p.add_argument("--top", type=int, default=12)
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-download", action="store_true",
                   help="do not fetch the open-source CJK families "
                        "(Noto / Source Han) that are not installed by "
                        "default.  Without them the matcher can only "
                        "compare against the system faces, which is not a "
                        "fair comparison.")
    p.add_argument("--font-dir",
                   help="where to store a downloaded font "
                        "(default: scripts/fonts)")
    p.set_defaults(func=cmd_fontid)

    p = sub.add_parser("geometry")
    p.add_argument("image")
    p.add_argument("--region", required=True,
                   help="x0,y0,x1,y1 of a generous box around the text")
    p.add_argument("--thr", type=float, default=None,
                   help="luminance threshold for ink detection")
    p.add_argument("--dark-thresh", type=int, default=0,
                   help="absolute luminance threshold (0 = off)")
    p.add_argument("--min-px", type=int, default=3,
                   help="minimum ink pixels per row/column to count")
    p.add_argument("--light-ink", action="store_true")
    p.set_defaults(func=cmd_geometry)

    p = sub.add_parser("verify")
    p.add_argument("image")
    p.add_argument("output")
    p.add_argument("--region", required=True)
    p.add_argument("--light-ink", action="store_true")
    p.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
