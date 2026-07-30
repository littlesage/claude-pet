# -*- coding: utf-8 -*-
"""펫 그림에서 바탕화면 아이콘(.ico)을 만든다.

투명 여백을 잘라내고 정사각으로 맞춰야 작은 크기에서도 캐릭터가 크게 보인다.
"""
import os
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
OUT = os.path.join(BASE, "ClaudePet.ico")
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def source_image():
    """대표 그림 — 정면으로 서 있는 모습을 우선 고른다."""
    for name in ("idle_1.png", "blink.png", "idle.png", "idle.webp", "sit.png"):
        path = os.path.join(ASSETS, name)
        if os.path.exists(path):
            im = Image.open(path)
            im.seek(0)
            return im.convert("RGBA"), name
    raise SystemExit("assets에서 쓸 만한 그림을 찾지 못했습니다")


im, used = source_image()
bbox = im.split()[3].point(lambda v: 255 if v >= 8 else 0).getbbox()
im = im.crop(bbox)

side = max(im.size) + max(im.size) // 12          # 사방에 약간 여백
canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
canvas.save(OUT, sizes=SIZES)
print(f"{used} → {OUT}")
print(f"  원본 {bbox} 잘라내고 {side}x{side} 정사각, {len(SIZES)}개 크기 포함")
