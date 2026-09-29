#!/usr/bin/env python3
"""paper-motion-kit: paper-craft motion graphics with Python (Pillow+numpy) + ffmpeg.

Commands: card | transition | join | overlay | subs | batch
Run `python pmk.py <cmd> -h` for options.
"""
import argparse, json, math, os, random, re, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ───────────────────────── themes ─────────────────────────
THEMES = {
    "watercolor": dict(bg=(243, 238, 226), paper=(253, 250, 243), ink=(58, 54, 68), sub=(112, 106, 124),
                       accent=(240, 98, 146), tape=(250, 214, 120),
                       bands=[(240, 98, 146), (126, 200, 196), (250, 214, 120), (166, 152, 222)]),
    "kraft": dict(bg=(214, 190, 150), paper=(240, 226, 198), ink=(70, 48, 34), sub=(120, 92, 66),
                  accent=(214, 72, 72), tape=(255, 235, 170),
                  bands=[(214, 72, 72), (96, 140, 110), (240, 200, 110), (110, 120, 170)]),
    "mono": dict(bg=(236, 236, 234), paper=(252, 252, 250), ink=(28, 28, 30), sub=(96, 96, 100),
                 accent=(255, 90, 130), tape=(225, 225, 220),
                 bands=[(255, 90, 130), (40, 40, 44), (200, 200, 196), (255, 90, 130)]),
}

FONT_MAIN = ["msjhbd.ttc", "NotoSansTC-VF.ttf", "NotoSansCJK-Bold.ttc", "PingFang.ttc", "Arial Unicode.ttf", "DejaVuSans-Bold.ttf"]
FONT_SUB = ["msjh.ttc", "NotoSansTC-VF.ttf", "NotoSansCJK-Regular.ttc", "PingFang.ttc", "Arial Unicode.ttf", "DejaVuSans.ttf"]
FONT_DIRS = ["C:/Windows/Fonts", str(Path.home() / "AppData/Local/Microsoft/Windows/Fonts"),
             "/System/Library/Fonts", "/Library/Fonts", "/usr/share/fonts", "/usr/share/fonts/truetype/noto"]


def find_font(names, size, font_path=None):
    if font_path:
        return ImageFont.truetype(font_path, size)
    for d in FONT_DIRS:
        for n in names:
            p = Path(d) / n
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), size)
                except OSError:
                    pass
    return ImageFont.load_default(size)


# ───────────────────────── math helpers ─────────────────────────
def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def out_cubic(x): return 1 - (1 - clamp(x)) ** 3
def in_cubic(x): return clamp(x) ** 3
def out_back(x, s=1.4):
    x = clamp(x) - 1; return 1 + (s + 1) * x ** 3 + s * x ** 2
def lerp(a, b, t): return a + (b - a) * t


def comp(dst, src, x, y):
    """alpha-composite src onto dst (both RGBA) at (x,y), clipping to bounds."""
    x, y = int(round(x)), int(round(y))
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + src.width, dst.width), min(y + src.height, dst.height)
    if x0 >= x1 or y0 >= y1:
        return
    dst.alpha_composite(src.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))


def fade(img, a):
    if a >= 0.999: return img
    img = img.copy(); img.putalpha(img.getchannel("A").point(lambda v: int(v * a))); return img


# ───────────────────────── paper primitives ─────────────────────────
_tex = {}
def paper_texture(w, h, base, seed=7, strength=1.0):
    key = (w, h, base, seed, strength)
    if key in _tex: return _tex[key]
    rng = np.random.default_rng(seed)
    grain = rng.normal(0, 1, (h, w)).astype(np.float32) * 2.6 * strength
    low = rng.normal(0, 1, (h // 90 + 2, w // 90 + 2)).astype(np.float32)
    low = np.array(Image.fromarray(low).resize((w, h), Image.BICUBIC)) * 1.8 * strength
    fib = Image.new("L", (w, h), 0); d = ImageDraw.Draw(fib)
    r = random.Random(seed)
    for _ in range(int(w * h / 9000)):
        x, y, l, a = r.uniform(0, w), r.uniform(0, h), r.uniform(6, 26), r.uniform(0, math.pi)
        d.line([(x, y), (x + l * math.cos(a), y + l * math.sin(a))], fill=r.randint(20, 70), width=1)
    fib = np.array(fib.filter(ImageFilter.GaussianBlur(.6)), np.float32) / 70 * 4 * strength
    arr = np.array(base, np.float32)[None, None, :] + (grain + low - fib)[:, :, None]
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    _tex[key] = im
    return im


def torn_mask(w, h, amp, rng, sides="tblr", ss=2):
    """mask (L, w x h) of a rectangle whose chosen sides have a torn, wobbly edge."""
    W, H, A = w * ss, h * ss, amp * ss
    def j(side): return rng.uniform(-A, A) if side else 0
    pts = []
    step = 11 * ss
    for x in range(0, W, step): pts.append((x, A + j("t" in sides)))
    for y in range(0, H, step): pts.append((W - A + j("r" in sides), y))
    for x in range(W, 0, -step): pts.append((x, H - A + j("b" in sides)))
    for y in range(H, 0, -step): pts.append((A + j("l" in sides), y))
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).polygon([(clamp(px, 0, W), clamp(py, 0, H)) for px, py in pts], fill=255)
    return m.resize((w, h), Image.LANCZOS)


def tape_piece(theme, s, rng, length=150, thick=46):
    tw, th = int(length * s), int(thick * s)
    im = Image.new("RGBA", (tw, th), (*theme["tape"], 205))
    d = ImageDraw.Draw(im)
    z = max(3, int(5 * s))
    for k in range(0, th, z * 2):  # zig-zag cut ends
        d.polygon([(0, k), (z, k + z), (0, k + 2 * z)], fill=(0, 0, 0, 0))
        d.polygon([(tw, k), (tw - z, k + z), (tw, k + 2 * z)], fill=(0, 0, 0, 0))
    for _ in range(int(tw * th / 260)):  # speckle
        d.point((rng.randint(0, tw - 1), rng.randint(0, th - 1)), fill=(255, 255, 255, rng.randint(20, 70)))
    return im


def pin(s, color=(214, 60, 70)):
    r = int(15 * s); S = r * 5; sz = 3
    im = Image.new("RGBA", (S * sz, S * sz), (0, 0, 0, 0)); d = ImageDraw.Draw(im); c = S * sz // 2
    d.ellipse([c - r * sz + 6 * sz, c - r * sz + 9 * sz, c + r * sz + 6 * sz, c + r * sz + 9 * sz], fill=(0, 0, 0, 70))
    im = im.filter(ImageFilter.GaussianBlur(3 * sz)); d = ImageDraw.Draw(im)
    d.ellipse([c - r * sz, c - r * sz, c + r * sz, c + r * sz], fill=(*color, 255))
    d.ellipse([c - r * sz * .55, c - r * sz * .6, c + r * sz * .05, c - r * sz * .05], fill=(255, 255, 255, 120))
    return im.resize((S, S), Image.LANCZOS)


def paper_sheet(w, h, theme, seed, margin, tape=True, pin_at=None, s=1.0, sides="tblr", amp=3, shadow=True):
    """Return RGBA (w+2m, h+2m): soft shadow + textured torn paper + tape/pin."""
    rng = random.Random(seed)
    m = int(margin)
    out = Image.new("RGBA", (w + 2 * m, h + 2 * m), (0, 0, 0, 0))
    mask = torn_mask(w, h, max(1, int(amp * s)), rng, sides)
    if shadow:
        sh = Image.new("L", out.size, 0); sh.paste(mask, (m, m + int(10 * s)))
        sh = sh.filter(ImageFilter.GaussianBlur(14 * s)).point(lambda v: int(v * .32))
        out.paste(Image.new("RGBA", out.size, (40, 30, 40, 255)), (0, 0), sh)
    tex = paper_texture(w, h, theme["paper"], seed).convert("RGBA")
    tex.putalpha(mask)
    out.alpha_composite(tex, (m, m))
    if tape:
        for cx, cy, ang in ((m + w * .12, m + 4 * s, rng.uniform(-38, -22)), (m + w * .88, m + 4 * s, rng.uniform(22, 38))):
            t = tape_piece(theme, s, rng).rotate(ang, expand=True, resample=Image.BICUBIC)
            comp(out, t, cx - t.width / 2, cy - t.height / 2)
    if pin_at:
        p = pin(s); comp(out, p, m + pin_at[0] - p.width / 2, m + pin_at[1] - p.height / 2)
    return out


def hand_ring(cx, cy, rx, ry, rng, n=140, turns=1.13):
    ph = [rng.uniform(0, 6.28) for _ in range(3)]
    st = rng.uniform(-2.4, -1.4)
    pts = []
    for i in range(n + 1):
        u = i / n; th = st + u * turns * 2 * math.pi
        k = 1 + .028 * math.sin(3 * th + ph[0]) + .02 * math.sin(5 * th + ph[1]) + .07 * u * u + .015 * math.sin(2 * th + ph[2])
        pts.append((cx + rx * k * math.cos(th), cy + ry * k * math.sin(th)))
    return pts


def draw_stroke(size, pts, p, color, width, ss=2):
    """progressively-drawn hand stroke, rendered supersampled then downscaled."""
    layer = Image.new("RGBA", (size[0] * ss, size[1] * ss), (0, 0, 0, 0))
    k = int(p * (len(pts) - 1)) + 1
    d = ImageDraw.Draw(layer); seg = [(x * ss, y * ss) for x, y in pts[:k]]
    if len(seg) > 1:
        w = int(width * ss)
        d.line(seg, fill=color, width=w, joint="curve")
        for e in (seg[0], seg[-1]):
            d.ellipse([e[0] - w / 2, e[1] - w / 2, e[0] + w / 2, e[1] + w / 2], fill=color)
    return layer.resize(size, Image.LANCZOS)


# ───────────────────────── frame sink (ffmpeg) ─────────────────────────
def ffmpeg_bin(): return shutil.which("ffmpeg") or sys.exit("ffmpeg not found in PATH")


def write_frames(frame_fn, n, fps, out, fmt, size):
    out = str(out)
    if fmt == "png":
        Path(out).mkdir(parents=True, exist_ok=True)
        for i in range(n): frame_fn(i / fps).save(Path(out) / f"f{i:05d}.png")
        return
    codec = {"mov": ["-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le"],
             "webm": ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", "-b:v", "0", "-crf", "20"],
             "mp4": ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-movflags", "+faststart"]}[fmt]
    cmd = [ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{size[0]}x{size[1]}",
           "-r", str(fps), "-i", "-", *codec, out]
    pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        pr.stdin.write(frame_fn(i / fps).tobytes())
    pr.stdin.close()
    if pr.wait(): sys.exit("ffmpeg failed")


def flatten(f, a):
    bg = paper_texture(f.width, f.height, THEMES[a.theme]["bg"], 3).convert("RGBA")
    bg.alpha_composite(f); return bg


def emit(a, frame_fn, dur, size):
    """shared: still / sequence / video output for card & transition."""
    flat = a.fmt == "mp4" or a.opaque
    fn = (lambda t: flatten(frame_fn(t), a)) if flat else frame_fn
    if a.still is not None:
        fn(a.still).save(a.out); print("still ->", a.out); return
    n = max(1, int(round(dur * a.fps)))
    write_frames(fn, n, a.fps, a.out, a.fmt, size)
    print("ok ->", a.out, f"({n} frames @ {a.fps}fps)")


# ───────────────────────── card ─────────────────────────
def cmd_card(a):
    th = THEMES[a.theme]; W, H = a.width, a.height; S = H / 1080
    lines = a.text.replace("\\n", "\n").split("\n")
    fs = int((a.size or {"title": 104, "lower": 66, "note": 48}[a.layout]) * S)
    fm = find_font(FONT_MAIN, fs, a.font); fsub = find_font(FONT_SUB, int(fs * .46), a.font)
    lh = int(fs * 1.28); padx, pady = int(fs * .9), int(fs * .62)
    tw = max(fm.getlength(l) for l in lines)
    subs = a.sub.replace("\\n", "\n").split("\n") if a.sub else []
    if subs: tw = max(tw, max(fsub.getlength(l) for l in subs))
    cw = int(max(tw + 2 * padx, W * (.42 if a.layout == "title" else .2)))
    sub_h = int(len(subs) * fs * .62 + (fs * .12 if subs else 0))
    ch = int(len(lines) * lh + sub_h + 2 * pady)
    m = int(60 * S)
    sheet = paper_sheet(cw, ch, th, a.seed, m, tape=not a.pin, pin_at=(cw / 2, 6 * S) if a.pin else None, s=S)
    gw, gh = sheet.size
    tl = Image.new("RGBA", (gw, gh), (0, 0, 0, 0)); d = ImageDraw.Draw(tl)  # crisp text layer, group coords
    y = m + pady; hl = None
    for l in lines:
        x = m + (cw - fm.getlength(l)) / 2
        d.text((x, y), l, font=fm, fill=(*th["ink"], 255))
        if a.highlight and a.highlight in l and hl is None:
            pre = fm.getlength(l[:l.index(a.highlight)]); wd = fm.getlength(a.highlight)
            hl = (x + pre + wd / 2, y + fs * .62, wd / 2 + fs * .42, fs * .62)
        y += lh
    y += fs * .08
    for l in subs:
        d.text((m + (cw - fsub.getlength(l)) / 2, y), l, font=fsub, fill=(*th["sub"], 255)); y += fs * .62
    ring = hand_ring(*hl, random.Random(a.seed)) if hl else None
    ccol = (*th["accent"], 215)
    anchor = {"title": (W / 2, H / 2), "lower": (W * .06 + gw / 2, H * .90 - gh / 2 + m * .6),
              "note": (W - W * .06 - gw / 2, H * .18 + gh / 2)}[a.layout]
    if a.x is not None: anchor = (a.x * W, anchor[1])
    if a.y is not None: anchor = (anchor[0], a.y * H)
    T, tin, tout = a.duration, a.tin, a.tout
    tc = tin + .25

    def frame(t):
        e_in = clamp(t / tin); q = clamp((t - (T - tout)) / tout)
        scale = (.88 + .12 * out_back(e_in)) * (1 - .04 * q); alpha = out_cubic(e_in) * (1 - q)
        g = sheet.copy()
        ta = out_cubic((t - .18) / .45)
        if ta > 0: comp(g, fade(tl, ta), 0, (1 - ta) * 22 * S)
        if ring and t > tc:
            comp(g, draw_stroke((gw, gh), ring, out_cubic((t - tc) / a.circle_time), ccol, max(4, 9 * S)), 0, 0)
        if abs(scale - 1) > 1e-3: g = g.resize((max(1, int(gw * scale)), max(1, int(gh * scale))), Image.LANCZOS)
        g = fade(g, alpha)
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        comp(canvas, g, anchor[0] - g.width / 2, anchor[1] - g.height / 2 - q * 18 * S)
        return canvas
    emit(a, frame, T, (W, H))


# ───────────────────────── transitions ─────────────────────────
def cmd_transition(a):
    th = THEMES[a.theme]; W, H = a.width, a.height; S = H / 1080
    E = int(150 * S); rng = random.Random(a.seed); D = a.duration; m0 = int(40 * S)

    def ph(t):  # cover-in (0-.45), hold (.45-.55), reveal-out (.55-1)
        p = t / D
        return ("in", p / .45) if p < .45 else (("hold", 1) if p < .55 else ("out", (p - .55) / .45))

    if a.style == "tape":
        sheet = paper_sheet(W + 2 * E, H + 80, th, a.seed, m0, tape=False, s=S, sides="lr", amp=7)
        for yy in (.18, .5, .82):  # tape strips over both torn edges
            for xx, ang in ((E * .9, -80), (E + W + E * .1, 80)):
                tp = tape_piece(th, S, rng, length=190).rotate(ang + rng.uniform(-6, 6), expand=True, resample=Image.BICUBIC)
                comp(sheet, tp, m0 + xx - tp.width / 2, m0 + 40 + H * yy - tp.height / 2)

        def frame(t):
            k, p = ph(t)
            x = lerp(W, -E, out_cubic(p)) if k == "in" else -E if k == "hold" else lerp(-E, -(W + 2 * E) - 2 * m0, in_cubic(p))
            c = Image.new("RGBA", (W, H), (0, 0, 0, 0)); comp(c, sheet, x - m0, -m0 - 40); return c

    elif a.style == "pin":
        sheet = paper_sheet(W + 2 * E, H + 2 * E, th, a.seed, m0, tape=False, pin_at=((W + 2 * E) / 2, H * .1 + E), s=S, amp=6)

        def frame(t):
            k, p = ph(t)
            if k == "in": sc, rot, dy = lerp(.12, 1.0, out_back(p, 1.1)), lerp(-14, 0, out_cubic(p)), 0
            elif k == "hold": sc, rot, dy = 1.0, 0, 0
            else: sc, rot, dy = 1.0, lerp(0, 4, in_cubic(p)), -in_cubic(p) * (H + 2 * E + 2 * m0)
            im = sheet.resize((int(sheet.width * sc), int(sheet.height * sc)), Image.BILINEAR) if sc != 1 else sheet
            if rot: im = im.rotate(rot, expand=True, resample=Image.BILINEAR)
            if k == "in": im = fade(im, clamp(p * 4))
            c = Image.new("RGBA", (W, H), (0, 0, 0, 0)); comp(c, im, W / 2 - im.width / 2, H / 2 - im.height / 2 + dy); return c

    else:  # line: hand-drawn colour bands sweep across, staggered
        N = 7; bh = H / N; stag = .07; bands = []
        for i in range(N):
            col = th["bands"][i % len(th["bands"])] if i % 2 == 0 else th["paper"]
            bw, bH = W + 2 * E, int(bh + 22 * S)
            b = Image.new("RGBA", (bw, bH), (*col, 255)); b.putalpha(torn_mask(bw, bH, int(6 * S), rng, "tblr"))
            bands.append(b)

        def frame(t):
            k, p = ph(t); c = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            for i, b in enumerate(bands):
                u = clamp((p - i * stag) / (1 - (N - 1) * stag))
                x = lerp(W, -E, out_cubic(u)) if k == "in" else -E if k == "hold" else lerp(-E, -(W + 2 * E), in_cubic(u))
                comp(c, b, x, i * bh - 11 * S)
            return c
    emit(a, frame, D, (W, H))


# ───────────────────────── ffprobe / join / overlay ─────────────────────────
def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                        "-of", "json", str(path)], capture_output=True, text=True)
    j = json.loads(r.stdout)
    return float(j["format"]["duration"]), {s["codec_type"] for s in j["streams"]}


def run_ff(args):
    if subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", *args]).returncode: sys.exit("ffmpeg failed")


def cmd_join(a):
    """A + B with a paper transition hiding the cut. Result length = len(A)+len(B)."""
    W, H, F = a.width, a.height, a.fps
    tmp = Path(tempfile.mkdtemp()); ov = tmp / "t.mov"
    cmd_transition(argparse.Namespace(style=a.style, theme=a.theme, width=W, height=H, fps=F, duration=a.duration, seed=a.seed,
                                      out=str(ov), fmt="mov", still=None, opaque=False))
    da, sa = probe(a.a); _, sb = probe(a.b); start = max(0, da - a.duration / 2)
    norm = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={F},format=yuv420p"
    fc = (f"[0:v]{norm}[a];[1:v]{norm}[b];[a][b]concat=n=2:v=1:a=0[v];"
          f"[2:v]format=rgba,setpts=PTS+{start}/TB[o];[v][o]overlay=eof_action=pass[vo]")
    maps = ["-map", "[vo]"]
    if "audio" in sa and "audio" in sb:
        fc += (";[0:a]aresample=48000,aformat=channel_layouts=stereo[a0];[1:a]aresample=48000,aformat=channel_layouts=stereo[a1];"
               "[a0][a1]concat=n=2:v=0:a=1[ao]")
        maps += ["-map", "[ao]", "-c:a", "aac", "-b:a", "192k"]
    run_ff(["-i", a.a, "-i", a.b, "-i", str(ov), "-filter_complex", fc, *maps, "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p", a.out])
    shutil.rmtree(tmp, ignore_errors=True); print("ok ->", a.out)


def cmd_overlay(a):
    """place an alpha overlay clip (card/transition) on a base video at time --at."""
    fc = f"[1:v]format=rgba,setpts=PTS+{a.at}/TB[o];[0:v][o]overlay=eof_action=pass:format=auto[v]"
    _, s = probe(a.base)
    run_ff(["-i", a.base, "-i", a.overlay, "-filter_complex", fc, "-map", "[v]", *(["-map", "0:a", "-c:a", "copy"] if "audio" in s else []),
            "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p", a.out])
    print("ok ->", a.out)


# ───────────────────────── bilingual subtitles ─────────────────────────
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
def ts(s):
    h, m, r = s.split(":"); sec, ms = r.replace(",", ".").split("."); return int(h) * 3600 + int(m) * 60 + int(sec) + float("0." + ms)
def parse_srt(p):
    out = []
    for blk in re.split(r"\n\s*\n", Path(p).read_text(encoding="utf-8-sig").replace("\r", "").strip()):
        ls = blk.split("\n")
        i = next((k for k, l in enumerate(ls) if "-->" in l), None)
        if i is None: continue
        s, e = [ts(x.strip()) for x in ls[i].split("-->")]
        out.append((s, e, [l.strip() for l in ls[i + 1:] if l.strip()]))
    return out
def ass_t(t): return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"
def bgr(c, a=0): return f"&H{a:02X}{c[2]:02X}{c[1]:02X}{c[0]:02X}&"


def cmd_subs(a):
    th = THEMES[a.theme]; H = a.height; W = int(H * 16 / 9)
    A = parse_srt(a.srt)
    if a.srt2:  # two files: primary + secondary, matched by index
        B = parse_srt(a.srt2)
        ev = [(s, e, " ".join(t), " ".join(B[i][2]) if i < len(B) else "") for i, (s, e, t) in enumerate(A)]
    else:  # one file, each cue = zh + en lines (any order)
        ev = []
        for s, e, t in A:
            z = [l for l in t if CJK.search(l)]; o = [l for l in t if not CJK.search(l)]
            ev.append((s, e, " ".join(z), " ".join(o)) if z and o else (s, e, " ".join(t), ""))
    zf = int(a.zh_size * H / 1080); ef = int(zf * .62)
    box = bgr(th["paper"], 0x14)
    style = (f"Style: Bi,{a.font},{zf},{bgr(th['ink'])},{bgr(th['ink'])},{box if a.box else bgr(th['paper'])},"
             f"{box if a.box else '&H00000000&'},-1,0,0,0,100,100,1,0,{3 if a.box else 1},{int(zf * .28) if a.box else 3},0,2,"
             f"{int(W * .08)},{int(W * .08)},{int(H * .06)},1")
    hdr = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
           "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,"
           "Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
           f"{style}\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    lines = []
    for s, e, z, o in ev:
        txt = z + (f"\\N{{\\fs{ef}\\c{bgr(th['sub'])}\\b0}}{o}" if o else "")
        lines.append(f"Dialogue: 0,{ass_t(s)},{ass_t(e)},Bi,,0,0,0,,{{\\fad(120,120)}}{txt}")
    Path(a.out_ass).write_text(hdr + "\n".join(lines) + "\n", encoding="utf-8")
    print("ass ->", a.out_ass)
    if a.video:
        ap = Path(a.out_ass).resolve()
        fd = ":fontsdir=C\\\\:/Windows/Fonts" if os.name == "nt" else ""
        r = subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(Path(a.video).resolve()), "-vf", f"ass={ap.name}{fd}",
                            "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "copy", str(Path(a.out).resolve())], cwd=ap.parent)
        if r.returncode: sys.exit("burn-in failed")
        print("ok ->", a.out)


# ───────────────────────── batch ─────────────────────────
def cmd_batch(a):
    for it in json.loads(Path(a.spec).read_text(encoding="utf-8")):
        it = dict(it); c = it.pop("cmd"); argv = [c]
        pos = it.pop("args", [])
        argv += [str(x) for x in pos]
        for k, v in it.items():
            k = "--" + k.replace("_", "-")
            if v is True: argv.append(k)
            elif v is not False: argv += [k, str(v)]
        print(">>", " ".join(argv)); main(argv)


# ───────────────────────── cli ─────────────────────────
def common(p):
    p.add_argument("--theme", default="watercolor", choices=THEMES)
    p.add_argument("--width", type=int, default=1920); p.add_argument("--height", type=int, default=1080)
    p.add_argument("--fps", type=int, default=30); p.add_argument("--seed", type=int, default=7)


def emit_args(p):
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--fmt", default="mov", choices=["mov", "webm", "mp4", "png"],
                   help="mov=ProRes4444 alpha (default), webm=VP9 alpha, mp4=opaque on paper bg, png=sequence dir")
    p.add_argument("--opaque", action="store_true", help="flatten onto paper background")
    p.add_argument("--still", type=float, help="write a single PNG at this time (preview)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pmk"); sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("card", help="animated paper title / lower-third / note card with pink circle highlight")
    common(p); emit_args(p)
    p.add_argument("text"); p.add_argument("--sub", help="secondary line(s), e.g. English subtitle")
    p.add_argument("--layout", default="title", choices=["title", "lower", "note"])
    p.add_argument("--highlight", help="substring of text to circle in pink")
    p.add_argument("--pin", action="store_true", help="pin instead of tape"); p.add_argument("--size", type=int)
    p.add_argument("--font"); p.add_argument("--duration", type=float, default=3.5)
    p.add_argument("--tin", type=float, default=.55); p.add_argument("--tout", type=float, default=.4)
    p.add_argument("--circle-time", type=float, default=.7)
    p.add_argument("--x", type=float, help="centre x (0-1)"); p.add_argument("--y", type=float, help="centre y (0-1)")
    p.set_defaults(fn=cmd_card)
    p = sp.add_parser("transition", help="paper transition: tape | pin | line (alpha overlay clip)")
    common(p); emit_args(p)
    p.add_argument("--style", default="tape", choices=["tape", "pin", "line"]); p.add_argument("--duration", type=float, default=1.1)
    p.set_defaults(fn=cmd_transition)
    p = sp.add_parser("join", help="concat two clips, hide the cut under a paper transition")
    common(p); p.add_argument("a"); p.add_argument("b"); p.add_argument("-o", "--out", required=True)
    p.add_argument("--style", default="tape", choices=["tape", "pin", "line"]); p.add_argument("--duration", type=float, default=1.1)
    p.set_defaults(fn=cmd_join)
    p = sp.add_parser("overlay", help="composite alpha clip onto video at --at seconds")
    p.add_argument("base"); p.add_argument("overlay"); p.add_argument("--at", type=float, default=0); p.add_argument("-o", "--out", required=True)
    p.set_defaults(fn=cmd_overlay)
    p = sp.add_parser("subs", help="bilingual SRT -> styled ASS (+ optional burn-in)")
    p.add_argument("srt", help="SRT; each cue has zh+en lines unless --srt2 given"); p.add_argument("--srt2")
    p.add_argument("--theme", default="watercolor", choices=THEMES); p.add_argument("--height", type=int, default=1080)
    p.add_argument("--font", default="Microsoft JhengHei"); p.add_argument("--zh-size", type=int, default=54)
    p.add_argument("--box", action="store_true", help="paper-coloured translucent box behind text")
    p.add_argument("--out-ass", default="subs.ass"); p.add_argument("--video"); p.add_argument("-o", "--out", default="subbed.mp4")
    p.set_defaults(fn=cmd_subs)
    p = sp.add_parser("batch", help="run a JSON list of {cmd, args?, ...options}"); p.add_argument("spec"); p.set_defaults(fn=cmd_batch)
    a = ap.parse_args(argv); a.fn(a)


if __name__ == "__main__":
    main()
