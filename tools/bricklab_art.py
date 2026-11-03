# Renders Bricklab's static artwork from the mark: the KNULLI Ports images
# (bricklab-image.png 512x512, bricklab-marquee.png 1000x220) and the site
# lockup. Usage: python3 tools/bricklab_art.py <Inter variable font> <out folder>
import os
import sys

from PIL import Image, ImageDraw, ImageFont

FONT, OUT = sys.argv[1], sys.argv[2]
NAVY = (22, 36, 76)
CREAM = (230, 229, 224)
WORD = (231, 222, 208)
TEAL = (41, 174, 184)
DARK = (21, 21, 21)
PAPER = (233, 231, 226)
SS = 2


def font(px):
    f = ImageFont.truetype(FONT, px)
    try:
        f.set_variation_by_axes([32, 700])
    except Exception:
        pass
    return f


def grid(d, x0, y0, k, gap, key, lit, rad):
    for i in range(16):
        r, c = divmod(i, 4)
        x, y = x0 + c * (k + gap), y0 + r * (k + gap)
        d.rounded_rectangle([x, y, x + k, y + k], radius=rad, fill=lit if i == 0 else key)


def render(w, h, bg, key, lit, word, layout):
    im = Image.new("RGBA", (w * SS, h * SS), bg)
    d = ImageDraw.Draw(im)
    if layout == "square":                      # mark only, centred
        k, gap = 90 * SS, 14 * SS
        g = 4 * k + 3 * gap
        grid(d, (w * SS - g) // 2, (h * SS - g) // 2, k, gap, key, lit, 11 * SS)
    elif layout == "marquee":                   # mark left, wordmark right
        k, gap = 40 * SS, 6 * SS
        g = 4 * k + 3 * gap
        grid(d, 30 * SS, (h * SS - g) // 2, k, gap, key, lit, 5 * SS)
        f = font(112 * SS)
        bb = f.getbbox("bricklab")
        d.text((30 * SS + g + 40 * SS, (h * SS - (bb[3] - bb[1])) // 2 - bb[1]), "bricklab", font=f, fill=word)
    else:                                       # lockup: mark above wordmark
        k, gap = 70 * SS, 10 * SS
        g = 4 * k + 3 * gap
        grid(d, (w * SS - g) // 2, 40 * SS, k, gap, key, lit, 9 * SS)
        f = font(96 * SS)
        bb = f.getbbox("bricklab")
        d.text(((w * SS - (bb[2] - bb[0])) // 2 - bb[0], 40 * SS + g + 30 * SS - bb[1]), "bricklab", font=f, fill=word)
    im = im.resize((w, h), Image.LANCZOS)
    return im if len(bg) == 4 else im.convert("RGB")


def main():
    os.makedirs(OUT, exist_ok=True)
    render(512, 512, PAPER, DARK, TEAL, DARK, "square").save(os.path.join(OUT, "bricklab-image.png"))
    render(1000, 220, (0, 0, 0, 0), CREAM, TEAL, PAPER, "marquee").save(os.path.join(OUT, "bricklab-marquee.png"))
    render(640, 500, NAVY, CREAM, TEAL, WORD, "lockup").save(os.path.join(OUT, "bricklab-lockup.png"))
    print("wrote 3 files to", OUT)


if __name__ == "__main__":
    main()
