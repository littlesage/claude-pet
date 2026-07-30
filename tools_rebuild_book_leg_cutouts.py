import argparse
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image


BASE = Path(__file__).resolve().parent
GENERATED = Path.home() / ".codex" / "generated_images" / "019fae4b-c586-7ac1-8b51-040713d9f514"

ACTION_SPECS = {
    "book": {
        "source": GENERATED / "call_Dq9f7cCw4sape2g6SBlJdcCL.png",
        "grid": (3, 2),
        "offsets": [(-40, -10), (-7, -5), (26, -2), (-40, 10), (-7, -2), (28, 8)],
    },
    "leg_swing": {
        "source": GENERATED / "call_i5tCartUyzCQeefMtCT2qnwI.png",
        "grid": (2, 2),
        "offsets": [(-22, -2), (-2, -8), (-22, 4), (-12, 3)],
    },
}


def green_key_mask(rgb):
    pixels = np.asarray(rgb)
    red = pixels[:, :, 0].astype(np.int16)
    green = pixels[:, :, 1].astype(np.int16)
    blue = pixels[:, :, 2].astype(np.int16)

    # Mint details have similar green and blue levels. The generated key is
    # distinctly greener than both neighboring channels.
    candidate = (green > 70) & (green - red > 10) & (green - blue > 10)
    height, width = candidate.shape
    outside = np.zeros_like(candidate)
    queue = deque()

    for x in range(width):
        queue.extend(((x, 0), (x, height - 1)))
    for y in range(height):
        queue.extend(((0, y), (width - 1, y)))

    while queue:
        x, y = queue.popleft()
        if outside[y, x] or not candidate[y, x]:
            continue
        outside[y, x] = True
        if x:
            queue.append((x - 1, y))
        if x + 1 < width:
            queue.append((x + 1, y))
        if y:
            queue.append((x, y - 1))
        if y + 1 < height:
            queue.append((x, y + 1))

    return np.where(outside, 0, 255).astype(np.uint8)


def extract_frame(cell, offset):
    alpha = Image.fromarray(green_key_mask(cell), "L")
    rgba = cell.convert("RGBA")
    rgba.putalpha(alpha)
    rgba = rgba.resize((256, 256), Image.Resampling.LANCZOS)

    data = np.asarray(rgba).copy()
    data[:, :, 3] = np.where(data[:, :, 3] >= 128, 255, 0)

    opaque = data[:, :, 3] == 255
    near_clear = ~opaque
    for _ in range(2):
        expanded = near_clear.copy()
        expanded[1:, :] |= near_clear[:-1, :]
        expanded[:-1, :] |= near_clear[1:, :]
        expanded[:, 1:] |= near_clear[:, :-1]
        expanded[:, :-1] |= near_clear[:, 1:]
        near_clear = expanded

    red = data[:, :, 0].astype(np.int16)
    green = data[:, :, 1].astype(np.int16)
    blue = data[:, :, 2].astype(np.int16)
    spill = opaque & near_clear & (green - red > 25) & (green - blue > 25)
    y_coords = np.indices(opaque.shape)[0]
    hair_spill = (
        opaque
        & near_clear
        & (y_coords < 150)
        & (green - red > 8)
        & (green - blue > 8)
    )
    spill |= hair_spill
    neutral = np.maximum(red, blue).astype(np.uint8)
    data[:, :, 1] = np.where(spill, neutral, data[:, :, 1])
    rgba = Image.fromarray(data, "RGBA")

    frame = Image.new("RGBA", (256, 256))
    frame.alpha_composite(rgba, offset)
    return frame


def rebuild(action, output_root):
    spec = ACTION_SPECS[action]
    source = Image.open(spec["source"]).convert("RGB")
    columns, rows = spec["grid"]
    cell_width = source.width // columns
    cell_height = source.height // rows
    output_dir = output_root / action
    output_dir.mkdir(parents=True, exist_ok=True)

    frame_number = 0
    for row in range(rows):
        for column in range(columns):
            frame_number += 1
            box = (
                column * cell_width,
                row * cell_height,
                (column + 1) * cell_width,
                (row + 1) * cell_height,
            )
            cell = source.crop(box)
            frame = extract_frame(cell, spec["offsets"][frame_number - 1])
            frame.save(output_dir / f"{frame_number:02}.png", optimize=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=BASE / "tmp" / "rebuilt_cutouts",
        help="Root directory for rebuilt action folders.",
    )
    args = parser.parse_args()

    for action in ACTION_SPECS:
        rebuild(action, args.output)
        print(f"rebuilt {action} -> {args.output / action}")


if __name__ == "__main__":
    main()
