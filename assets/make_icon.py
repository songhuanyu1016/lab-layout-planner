"""Generate assets/icon.ico (and icon.png) for Lab Layout Planner.

Design: a top-down layout workspace. Inch rulers run along the top and left
edges (as in the app), framing an optical table with a hole grid. Coloured
component footprints - including an irregular CAD silhouette - are arranged
on it; one is selected (dashed box, handles, rotate arrow) and being dragged
by the cursor, and a dimension annotation measures the gap between two parts.
16-32 px frames use a simplified, bolder drawing.

Run:  python assets/make_icon.py
"""
import math
import os
from PIL import Image, ImageDraw, ImageFilter, ImageChops

HERE = os.path.dirname(os.path.abspath(__file__))
S = 1024
TILE = [24, 24, S - 24, S - 24]
TILE_R = 220


# ---------------------------------------------------------------- helpers
def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def grad(a, b, angle=90):
    """Full-canvas linear gradient; angle 90 = top -> bottom."""
    small = Image.new("RGBA", (64, 64))
    px = small.load()
    ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    for y in range(64):
        for x in range(64):
            t = ((x - 32) * ca + (y - 32) * sa) / 45 + 0.5
            px[x, y] = lerp(a, b, min(max(t, 0), 1)) + (255,)
    return small.resize((S, S), Image.BILINEAR)


def new_mask(fn):
    m = Image.new("L", (S, S), 0)
    fn(ImageDraw.Draw(m))
    return m


def tile_mask():
    return new_mask(lambda d: d.rounded_rectangle(TILE, radius=TILE_R, fill=255))


def clip_to_tile(img):
    img.putalpha(ImageChops.multiply(img.getchannel("A"), tile_mask()))


def fill(img, src, mask):
    img.alpha_composite(Image.composite(src, Image.new("RGBA", (S, S), (0, 0, 0, 0)), mask))


def blur_layer(img, fn, radius, opacity=1.0):
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    fn(ImageDraw.Draw(layer))
    layer = layer.filter(ImageFilter.GaussianBlur(radius))
    if opacity < 1:
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * opacity)))
    img.alpha_composite(layer)


def drop_shadow(img, mask, dx=10, dy=18, blur=18, opacity=0.45):
    sh = ImageChops.offset(mask, dx, dy).filter(ImageFilter.GaussianBlur(blur))
    layer = Image.new("RGBA", (S, S), (6, 10, 30, 0))
    layer.putalpha(sh.point(lambda v: int(v * opacity)))
    img.alpha_composite(layer)


def part(img, shape_fn, top, bot, rim=(255, 255, 255, 170), rim_w=6):
    """Draw a component footprint: shadow, gradient body, light rim, sheen."""
    mask = new_mask(lambda d: shape_fn(d, 255))
    drop_shadow(img, mask)
    fill(img, grad(top, bot, 70), mask)
    ring = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shape_fn(ImageDraw.Draw(ring), None, outline=rim, width=rim_w)
    img.alpha_composite(ring)
    sheen = Image.new("RGBA", (S, S), (255, 255, 255, 0))
    sheen.putalpha(ImageChops.multiply(mask, grad((90,) * 3, (0,) * 3, 60).getchannel("R")))
    img.alpha_composite(sheen)


def rrect(box, r):
    def fn(d, f, outline=None, width=0):
        d.rounded_rectangle(box, radius=r, fill=f, outline=outline, width=width)
    return fn


def ellipse(box):
    def fn(d, f, outline=None, width=0):
        d.ellipse(box, fill=f, outline=outline, width=width)
    return fn


def polyshape(pts):
    def fn(d, f, outline=None, width=0):
        if f is not None:
            d.polygon(pts, fill=f)
        if outline:
            d.line(pts + [pts[0]], fill=outline, width=width, joint="curve")
    return fn


def dashed_rect(d, box, color, width, dash=26, gap=16):
    x0, y0, x1, y1 = box
    for (ax, ay), (bx, by) in [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
                               ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]:
        length = math.hypot(bx - ax, by - ay)
        ux, uy = (bx - ax) / length, (by - ay) / length
        t = 0
        while t < length:
            e = min(t + dash, length)
            d.line([(ax + ux * t, ay + uy * t), (ax + ux * e, ay + uy * e)],
                   fill=color, width=width)
            t += dash + gap


# ---------------------------------------------------------------- layout
RUL = 92                       # ruler thickness
RX0, RY0 = 92, 92              # ruler origin (inside the tile)
TABLE = [232, 232, 892, 892]

BLUE = ((96, 170, 255), (40, 96, 230))
TEAL = ((90, 240, 200), (16, 160, 150))
ORANGE = ((255, 196, 92), (240, 120, 40))
PINK = ((255, 120, 170), (210, 50, 120))

LASER = [282, 286, 600, 436]
SILHOUETTE = [(660, 286), (842, 286), (842, 560), (770, 560), (770, 400),
              (700, 400), (700, 470), (660, 470)]
BOX = [282, 500, 446, 842]
SEL_C, SEL_R = (690, 720), 104


def background(img, small):
    fill(img, grad((40, 44, 120), (14, 18, 52), 70), tile_mask())
    if not small:
        g = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        gd = ImageDraw.Draw(g)
        for v in range(RX0 + RUL, S, 40):
            gd.line([(v, RY0 + RUL), (v, S)], fill=(140, 170, 255, 34), width=2)
            gd.line([(RX0 + RUL, v), (S, v)], fill=(140, 170, 255, 34), width=2)
        img.alpha_composite(g)
        blur_layer(img, lambda d: d.ellipse([140, 100, 900, 700], fill=(120, 110, 255, 60)), 120)
    clip_to_tile(img)


def rulers(img, small):
    band = new_mask(lambda dd: (dd.rectangle([RX0, RY0, S, RY0 + RUL], fill=255),
                                dd.rectangle([RX0, RY0, RX0 + RUL, S], fill=255)))
    band = ImageChops.multiply(band, tile_mask())
    drop_shadow(img, band, dx=0, dy=10, blur=16, opacity=0.5)
    fill(img, grad((255, 226, 120), (246, 178, 52), 45), band)
    d = ImageDraw.Draw(img)
    d.rectangle([RX0, RY0, RX0 + RUL, RY0 + RUL], fill=(232, 160, 40, 255))
    ink = (110, 70, 20, 255)
    if small:
        for v in range(RX0 + RUL + 80, S, 160):
            d.line([(v, RY0 + RUL - 44), (v, RY0 + RUL)], fill=ink, width=24)
            d.line([(RX0 + RUL - 44, v), (RX0 + RUL, v)], fill=ink, width=24)
    else:
        for i, v in enumerate(range(RX0 + RUL, S, 20)):
            L = 52 if i % 8 == 0 else 34 if i % 4 == 0 else 18
            w = 6 if i % 8 == 0 else 4
            d.line([(v, RY0 + RUL - L), (v, RY0 + RUL)], fill=ink, width=w)
            d.line([(RX0 + RUL - L, v), (RX0 + RUL, v)], fill=ink, width=w)
        # cursor-position markers on the rulers (as in the app)
        cx, cy = 742, 706
        d.polygon([(cx - 16, RY0 + 6), (cx + 16, RY0 + 6), (cx, RY0 + 30)], fill=(220, 40, 90, 255))
        d.polygon([(RX0 + 6, cy - 16), (RX0 + 6, cy + 16), (RX0 + 30, cy)], fill=(220, 40, 90, 255))
    clip_to_tile(img)


def table(img, small):
    m = ImageChops.multiply(new_mask(lambda d: d.rounded_rectangle(TABLE, radius=40, fill=255)),
                            tile_mask())
    drop_shadow(img, m, dx=0, dy=22, blur=30, opacity=0.6)
    fill(img, grad((236, 242, 252), (176, 190, 216), 60), m)
    ring = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(ring).rounded_rectangle(TABLE, radius=40, outline=(255, 255, 255, 220), width=6)
    img.alpha_composite(ring)
    if not small:
        d = ImageDraw.Draw(img)
        for x in range(TABLE[0] + 38, TABLE[2] - 20, 50):
            for y in range(TABLE[1] + 38, TABLE[3] - 20, 50):
                d.ellipse([x - 8, y - 6, x + 8, y + 10], fill=(255, 255, 255, 200))
                d.ellipse([x - 8, y - 8, x + 8, y + 8], fill=(124, 138, 168, 255))
    clip_to_tile(img)


def components(img, small):
    part(img, rrect(LASER, 26), *BLUE)
    part(img, polyshape(SILHOUETTE), *TEAL)
    part(img, rrect(BOX, 26), *ORANGE)
    cx, cy = SEL_C
    r = SEL_R if not small else SEL_R + 16
    part(img, ellipse([cx - r, cy - r, cx + r, cy + r]), *PINK)
    if not small:
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([600, 344, 628, 378], radius=6, fill=(30, 60, 150, 255))
        for k in range(4):
            x = 318 + k * 40
            d.rounded_rectangle([x, 318, x + 18, 404], radius=9, fill=(255, 255, 255, 110))
        for sx, sy in [(316, 534), (412, 534), (316, 808), (412, 808)]:
            d.ellipse([sx - 11, sy - 11, sx + 11, sy + 11], fill=(150, 70, 20, 255))
        d.ellipse([720, 320, 810, 380], outline=(255, 255, 255, 170), width=6)
        d.ellipse([cx - 46, cy - 46, cx + 46, cy + 46], outline=(255, 255, 255, 200), width=8)
        d.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], fill=(255, 255, 255, 230))


def selection(img):
    d = ImageDraw.Draw(img)
    cx, cy = SEL_C
    p = SEL_R + 26
    box = [cx - p, cy - p, cx + p, cy + p]
    dashed_rect(d, box, (255, 255, 255, 255), 6)
    for hx, hy in [(box[0], box[1]), (box[2], box[1]), (box[0], box[3]), (box[2], box[3])]:
        d.rectangle([hx - 14, hy - 14, hx + 14, hy + 14], fill=(255, 255, 255, 255),
                    outline=(220, 40, 90, 255), width=5)
    # rotate handle: curved arrow above the selection
    ax, ay, ar = cx, box[1] - 44, 52
    d.arc([ax - ar, ay - ar, ax + ar, ay + ar], 200, 340, fill=(255, 255, 255, 255), width=10)
    ex = ax + ar * math.cos(math.radians(340))
    ey = ay + ar * math.sin(math.radians(340))
    d.polygon([(ex + 18, ey - 18), (ex + 16, ey + 22), (ex - 20, ey + 4)], fill=(255, 255, 255, 255))


def dimension(img):
    """Measure annotation between the orange box and the pink part."""
    d = ImageDraw.Draw(img)
    y = 862
    x0, x1 = BOX[2], SEL_C[0] - SEL_R
    col = (255, 255, 255, 255)
    blur_layer(img, lambda dd: dd.line([(x0, y), (x1, y)], fill=(0, 0, 0, 255), width=8), 4, 0.5)
    d.line([(x0 + 4, y), (x1 - 4, y)], fill=col, width=6)
    for x in (x0, x1):
        d.line([(x, y - 30), (x, y + 24)], fill=col, width=6)
    d.polygon([(x0 + 4, y), (x0 + 30, y - 14), (x0 + 30, y + 14)], fill=col)
    d.polygon([(x1 - 4, y), (x1 - 30, y - 14), (x1 - 30, y + 14)], fill=col)


def cursor(img):
    """Arrow pointer dragging the selected part."""
    x, y, k = 742, 706, 1.25
    pts = [(0, 0), (0, 150), (38, 114), (64, 176), (92, 164), (66, 104), (116, 104)]
    pts = [(x + px * k, y + py * k) for px, py in pts]
    drop_shadow(img, new_mask(lambda d: d.polygon(pts, fill=255)), dx=8, dy=14, blur=10, opacity=0.6)
    d = ImageDraw.Draw(img)
    d.polygon(pts, fill=(255, 255, 255, 255))
    d.line(pts + [pts[0]], fill=(20, 24, 60, 255), width=9, joint="curve")
    clip_to_tile(img)


def gloss(img):
    g = new_mask(lambda d: d.ellipse([-260, -820, S + 260, 380], fill=46))
    g = ImageChops.multiply(g.filter(ImageFilter.GaussianBlur(30)), tile_mask())
    w = Image.new("RGBA", (S, S), (255, 255, 255, 0))
    w.putalpha(g)
    img.alpha_composite(w)
    ring = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(ring).rounded_rectangle(TILE, radius=TILE_R, outline=(255, 255, 255, 60), width=6)
    img.alpha_composite(ring)


def render(small=False):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    background(img, small)
    table(img, small)
    components(img, small)
    if not small:
        dimension(img)
        selection(img)
    rulers(img, small)
    if not small:
        cursor(img)
        gloss(img)
    return img


def main():
    full, small = render(False), render(True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [(small if s <= 32 else full).resize((s, s), Image.LANCZOS) for s in sizes]
    frames[-1].save(os.path.join(HERE, "icon.png"))
    frames[-1].save(os.path.join(HERE, "icon.ico"), format="ICO",
                    sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    print("Wrote icon.ico / icon.png in", HERE)


if __name__ == "__main__":
    main()
