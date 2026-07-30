import argparse
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image


BASE = Path(__file__).resolve().parent
GENERATED = Path.home() / ".codex" / "generated_images" / "019fae4b-c586-7ac1-8b51-040713d9f514"

ACTION_SPECS = {
    "bread": {
        "source": GENERATED / "call_LwoB8xJUaK3rNErDNRPty6wZ.png",
        "grid": (4, 2),
        "offsets": [
            (-28, -2),
            (-12, -2),
            (-2, 1),
            (9, 1),
            (-27, 2),
            (-14, -1),
            (-2, -3),
            (9, 2),
        ],
    },
    "book": {
        "source": GENERATED / "call_Dq9f7cCw4sape2g6SBlJdcCL.png",
        "grid": (3, 2),
        "offsets": [(-40, -10), (-7, -5), (26, -2), (-40, 10), (-7, -2), (28, 8)],
    },
    "game": {
        "source": GENERATED / "call_BgmQ41lA1h7RbluiaKpHbicd.png",
        "grid": (3, 2),
        "offsets": [(-42, -5), (-12, -6), (29, -6), (-42, 6), (-2, 5), (30, 6)],
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
    candidate = (green > 80) & (green - red > 25) & (green - blue > 35)
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


def remove_tiny_islands(data, max_area=10):
    opaque = data[:, :, 3] == 255
    visited = np.zeros_like(opaque)
    height, width = opaque.shape

    for start_y, start_x in zip(*np.where(opaque & ~visited)):
        if visited[start_y, start_x]:
            continue
        component = []
        queue = deque([(start_x, start_y)])
        while queue:
            x, y = queue.popleft()
            if visited[y, x] or not opaque[y, x]:
                continue
            visited[y, x] = True
            component.append((x, y))
            if x:
                queue.append((x - 1, y))
            if x + 1 < width:
                queue.append((x + 1, y))
            if y:
                queue.append((x, y - 1))
            if y + 1 < height:
                queue.append((x, y + 1))
        if len(component) <= max_area:
            for x, y in component:
                data[y, x, 3] = 0


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
    frame_data = np.asarray(frame).copy()
    remove_tiny_islands(frame_data)
    return Image.fromarray(frame_data, "RGBA")


def rebuild(action, output_root):
    spec = ACTION_SPECS[action]
    source = Image.open(spec["source"]).convert("RGB")
    columns, rows = spec["grid"]
    output_dir = output_root / action
    output_dir.mkdir(parents=True, exist_ok=True)

    frame_number = 0
    for row in range(rows):
        for column in range(columns):
            frame_number += 1
            box = (
                column * source.width // columns,
                row * source.height // rows,
                (column + 1) * source.width // columns,
                (row + 1) * source.height // rows,
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
