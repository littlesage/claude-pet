# -*- coding: utf-8 -*-
"""봉을 지운 프레임으로 hang.webp를 다시 만든다.

프레임 지속시간은 화면 갱신 주기의 배수로 맞춘다. 어긋나면 어떤 프레임은 한 틱 더
머물러 떨리는 것처럼 보인다.
"""
import glob
import os
import shutil
import sys
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
SRC = os.path.join(ASSETS, "_hang_nobar")
DST = os.path.join(ASSETS, "hang.webp")
DURATION = 100          # 25ms 틱 × 4

frames = [Image.open(f).convert("RGBA")
          for f in sorted(glob.glob(os.path.join(SRC, "hang_*.png")))]
if not frames:
    raise SystemExit(f"{SRC}에 프레임이 없습니다")

if os.path.exists(DST):
    backup = DST + ".bak"
    if not os.path.exists(backup):
        shutil.copy2(DST, backup)
        print(f"원본 백업: {backup}")

frames[0].save(DST, save_all=True, append_images=frames[1:],
               duration=DURATION, loop=0, lossless=True)
print(f"{len(frames)}프레임 × {DURATION}ms → {DST}")

check = Image.open(DST)
print(f"확인: {getattr(check, 'n_frames', 1)}프레임, "
      f"duration={check.info.get('duration')}ms, 크기={check.size}")
