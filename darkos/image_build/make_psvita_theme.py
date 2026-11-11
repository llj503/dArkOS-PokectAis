#!/usr/bin/env python3
"""Create a psvita folder for es-theme-nes-box.

The theme has no PlayStation Vita art, so the ES carousel row would be blank.
Render a plain wordmark with the theme's own font instead of borrowing PSP art.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

THEME = sys.argv[1] if len(sys.argv) > 1 else \
    "/home/ark/.emulationstation/themes/es-theme-nes-box"
OUT = os.path.join(THEME, "psvita")
FONT = os.path.join(THEME, "_inc/fonts/sans-black-cond-italic.ttf")

os.makedirs(OUT, exist_ok=True)


def wordmark(text, size, canvas, colour):
    font = ImageFont.truetype(FONT, size)
    im = Image.new("RGBA", canvas, (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    box = d.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((canvas[0] - w) / 2 - box[0], (canvas[1] - h) / 2 - box[1]),
           text, font=font, fill=colour)
    return im


# system.png: the carousel / game-list wordmark, same canvas as psp's.
logo = wordmark("PS VITA", 110, (480, 157), (255, 255, 255, 255))
logo.save(os.path.join(OUT, "system.png"))

# background_icon.png: the large faint backdrop, same canvas as psp's.
bg = wordmark("PS VITA", 200, (960, 540), (255, 255, 255, 60))
bg.save(os.path.join(OUT, "background_icon.png"))

with open(os.path.join(OUT, "theme.xml"), "w", encoding="utf-8") as fh:
    fh.write("""<theme>
\t<formatVersion>7</formatVersion>
\t<include>./../theme.xml</include>

\t<view name="system">
\t\t<image name="logo">
\t\t\t<path>./system.png</path>
\t\t</image>
\t\t<image name="background_icon" extra="true">
\t\t\t<zIndex>3</zIndex>
\t\t\t<path>./background_icon.png</path>
\t\t</image>
\t</view>

\t<view name="detailed, video">
\t\t<image name="system" extra="true">
\t\t\t<origin>0.5 0.5</origin>
\t\t\t<pos>0.75 0.138</pos>
\t\t\t<maxSize>0.4 0.14</maxSize>
\t\t\t<path>./system.png</path>
\t\t\t<zIndex>3</zIndex>
\t\t</image>
\t</view>
\t<view name="basic">
\t\t<image name="system" extra="true">
\t\t\t<origin>0.5 0</origin>
\t\t\t<pos>0.5 0.02</pos>
\t\t\t<maxSize>1 .12</maxSize>
\t\t\t<path>./system.png</path>
\t\t\t<zIndex>3</zIndex>
\t\t</image>
\t</view>
</theme>
""")
print("wrote", OUT)
for f in sorted(os.listdir(OUT)):
    print(" ", f, os.path.getsize(os.path.join(OUT, f)))