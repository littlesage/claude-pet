# -*- coding: utf-8 -*-
"""정지 sit 원본에서 아주 미세한 호흡 WebP를 만든다.

엉덩이 선 아래는 그대로 두고 상체 높이만 1~2px 바꿔, 창에 앉은 접점과 다리가
움직이지 않게 한다. 프레임 시간은 25ms 틱의 배수로 맞춘다.
"""
import os

from PIL import Image, ImageFilter


BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
SOURCE = os.path.join(ASSETS, "sit_base.png")
FRAMES_DIR = os.path.join(ASSETS, "sit_idle_frames")
OUTPUT = os.path.join(ASSETS, "sit.webp")

ANCHOR_Y = 186
HEIGHT_DELTAS = (0, 1, 2, 1, 0, -1)
DURATIONS = (500, 500, 650, 500, 500, 650)


def breathing_frame(source, delta):
    if delta == 0:
        return source.copy()
    upper = source.crop((0, 0, source.width, ANCHOR_Y))
    new_height = ANCHOR_Y + delta
    upper = upper.resize((source.width, new_height), Image.Resampling.LANCZOS)

    warped = source.copy()
    warped.paste((0, 0, 0, 0), (0, 0, source.width, ANCHOR_Y))
    warped.alpha_composite(upper, (0, ANCHOR_Y - new_height))

    # 가느다란 머리카락 끝과 외곽선은 원본 그대로 둔다. 내부 픽셀만 움직이면
    # 호흡은 보이면서 프레임 전환 때 누끼 경계가 깜빡이지 않는다.
    alpha = source.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
    interior = alpha.filter(ImageFilter.MinFilter(3))
    frame = Image.composite(warped, source, interior)
    frame.putalpha(alpha)
    return frame


def main():
    if not os.path.exists(SOURCE):
        raise SystemExit(f"원본이 없습니다: {SOURCE}")
    source = Image.open(SOURCE).convert("RGBA")
    if source.size != (256, 256):
        raise SystemExit(f"sit 원본은 256x256이어야 합니다: {source.size}")

    os.makedirs(FRAMES_DIR, exist_ok=True)
    frames = []
    for index, delta in enumerate(HEIGHT_DELTAS, 1):
        frame = breathing_frame(source, delta)
        frame.save(os.path.join(FRAMES_DIR, f"{index:02d}.png"), optimize=True)
        frames.append(frame)

    frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=frames[1:],
        duration=DURATIONS,
        loop=0,
        lossless=True,
        method=6,
        kmin=1,
        kmax=1,
    )
    print(f"{len(frames)}프레임 호흡 루프 -> {OUTPUT}")


if __name__ == "__main__":
    main()
