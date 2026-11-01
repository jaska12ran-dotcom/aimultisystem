"""Generate the self-contained media loops used by the NextWorld landing page.

The videos are procedural (no third-party footage) and are encoded with the
bundled FFmpeg from ``imageio-ffmpeg`` so the repository stays license-clean.

Usage:
    python scripts/generate_frontend_media.py

Outputs:
    frontend/public/media/nextworld.mp4   + nextworld-poster.jpg
    frontend/public/media/signal.mp4      + signal-poster.jpg
    frontend/public/media/orbital.mp4     + orbital-poster.jpg
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "media"
OUT.mkdir(parents=True, exist_ok=True)

FPS = 24
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\CascadiaMono.ttf",
    r"C:\Windows\Fonts\lucon.ttf",
]


def ffmpeg_bin() -> str:
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass

    # When installed into a temporary target directory by the setup command.
    temp = Path(tempfile.gettempdir()) / "opencode" / "pydeps"
    if temp.exists():
        sys.path.insert(0, str(temp))
        try:
            import imageio_ffmpeg  # type: ignore

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    raise RuntimeError("imageio-ffmpeg is required to encode the landing media.")


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if os.path.exists(candidate):
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def encode(frames, size: tuple[int, int], destination: Path) -> None:
    width, height = size
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "25",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "main",
        "-movflags",
        "+faststart",
        str(destination),
    ]
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert process.stdin is not None
    try:
        for frame in frames:
            process.stdin.write(frame.astype(np.uint8).tobytes())
        process.stdin.close()
    finally:
        stderr = process.stderr.read().decode("utf-8", "ignore") if process.stderr else ""
        code = process.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg failed ({code}): {stderr[-2000:]}")


def save_poster(frame: np.ndarray, destination: Path) -> None:
    Image.fromarray(frame.astype(np.uint8)).save(destination, quality=88, optimize=True)


# ---------------------------------------------------------------------------
# 1. NEXTWORLD — a slowly breathing wormhole / aurora tunnel
# ---------------------------------------------------------------------------

def save_nextworld() -> None:
    width, height = 960, 540
    total = FPS * 8
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    nx = (xx / width) * 2.0 - 1.0
    ny = (yy / height) * 2.0 - 1.0
    nx *= width / height
    r = np.sqrt(nx * nx + ny * ny) + 1e-5
    theta = np.arctan2(ny, nx)

    rng = np.random.default_rng(20261019)
    stars = rng.random((420, 4))
    star_x = (stars[:, 0] * width).astype(np.int32)
    star_y = (stars[:, 1] * height).astype(np.int32)
    star_phase = stars[:, 2] * math.tau
    star_power = 0.35 + stars[:, 3] * 0.65

    def frames():
        nonlocal poster
        for frame_index in range(total):
            t = frame_index / total
            angle = theta + 1.6 * t + 0.9 * np.sin(r * 3.0 - t * math.tau)
            warp = np.sin(14.0 * r - t * math.tau * 3.0 + 2.2 * np.sin(3.0 * angle + t * math.tau))
            warp2 = np.sin(7.0 * r + t * math.tau * 2.0 - 3.0 * np.cos(2.0 * angle - t * math.tau))
            ribbons = np.clip(warp * 0.55 + warp2 * 0.45, -1.0, 1.0)

            radial = np.exp(-((r - 0.18) ** 2) / 0.32) * np.clip(1.15 - r * 0.55, 0.0, 1.0)
            core = np.exp(-(r**2) / 0.018)
            ring = np.clip(np.abs(ribbons) - 0.62, 0.0, 1.0) * 4.2 * radial

            cyan = np.clip(ring * (0.55 + 0.45 * np.sin(angle * 2.0 + t * math.tau)), 0.0, 1.0)
            violet = np.clip(ring * (0.55 + 0.45 * np.cos(angle * 3.0 - t * math.tau)), 0.0, 1.0)
            amber = np.clip((ribbons * 0.5 + 0.5) ** 4 * radial * 0.8, 0.0, 1.0)

            image = np.zeros((height, width, 3), dtype=np.float32)
            image += np.stack([core * 0.75, core * 0.95, core], axis=-1)
            image += np.stack([cyan * 0.04, cyan * 0.72, cyan * 0.9], axis=-1)
            image += np.stack([violet * 0.62, violet * 0.16, violet * 0.95], axis=-1)
            image += np.stack([amber * 0.95, amber * 0.52, amber * 0.18], axis=-1)

            haze = np.clip(0.12 - r * 0.025, 0.0, 0.12)
            image += np.stack([haze * 0.3, haze * 0.55, haze], axis=-1)

            twinkle = 0.4 + 0.6 * (0.5 + 0.5 * np.sin(star_phase + t * math.tau * 2.0))
            for index in range(0, len(star_x), 2):
                x = star_x[index]
                y = star_y[index]
                power = star_power[index] * twinkle[index]
                image[y, x] += np.array([0.45, 0.7, 1.0], dtype=np.float32) * power * 0.7
                if r[y, x] > 0.55:
                    image[y, max(0, x - 2) : x + 3] += np.array([0.1, 0.3, 0.55], dtype=np.float32) * power * 0.25

            vignette = np.clip(1.25 - r * 0.55, 0.0, 1.0) ** 1.6
            image *= vignette[..., None]

            grain = rng.normal(0.0, 0.018, (height, width, 1)).astype(np.float32)
            image = np.clip(image + grain, 0.0, 1.0)
            frame = (image ** (1 / 1.35) * 255.0).clip(0, 255)
            if frame_index == total // 3:
                poster = frame.copy()
            yield frame

    poster = None
    encode(frames(), (width, height), OUT / "nextworld.mp4")
    assert poster is not None
    save_poster(poster, OUT / "nextworld-poster.jpg")


# ---------------------------------------------------------------------------
# 2. SIGNAL — a live code/telemetry waterfall
# ---------------------------------------------------------------------------

def save_signal() -> None:
    width, height = 540, 720
    total = FPS * 6
    mono = font(20)
    mono_small = font(13)
    mono_big = font(34)
    rng = np.random.default_rng(77)
    alphabet = "01{}[]()<>/\\|;:=+-*#$%&@ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    columns = []
    for index in range(14):
        columns.append(
            {
                "x": 18 + index * 38,
                "y": rng.uniform(-1.4, 1.0),
                "speed": rng.uniform(0.18, 0.5),
                "length": int(rng.integers(8, 20)),
                "seed": int(rng.integers(0, 999999)),
            }
        )

    poster = None
    def frames():
        nonlocal poster
        for frame_index in range(total):
            t = frame_index / total
            base = Image.new("RGB", (width, height), (3, 6, 12))
            draw = ImageDraw.Draw(base)

            # Atmospheric glow washes.
            glow = Image.new("RGB", (width, height), (0, 0, 0))
            gdraw = ImageDraw.Draw(glow)
            gdraw.ellipse((width * 0.1, height * 0.05, width * 0.9, height * 0.65), fill=(3, 18, 38))
            gdraw.ellipse((width * 0.25, height * 0.55, width * 1.0, height * 1.05), fill=(24, 6, 40))
            glow = glow.filter(ImageFilter.GaussianBlur(90))
            base = Image.blend(base, Image.blend(base, glow, 0.8), 0.9)
            draw = ImageDraw.Draw(base)

            # Faint grid.
            for x in range(0, width, 45):
                draw.line((x, 0, x, height), fill=(8, 22, 34), width=1)
            for y in range(0, height, 45):
                draw.line((0, y, width, y), fill=(8, 20, 30), width=1)

            # Rain columns.
            for column in columns:
                column["y"] += column["speed"] * 0.032
                if column["y"] > 1.25:
                    column["y"] = -0.25
                    column["seed"] = int(rng.integers(0, 999999))
                head = int(column["y"] * height)
                for line in range(column["length"]):
                    y = head - line * 22
                    if -22 < y < height:
                        local = (column["seed"] + line * 97 + frame_index // 3 * 13) % len(alphabet)
                        char = alphabet[local]
                        intensity = max(0.0, 1.0 - line / column["length"])
                        if line == 0:
                            color = (210, 255, 250)
                        elif line < 3:
                            color = (
                                int(90 + 120 * intensity),
                                int(235 + 20 * intensity),
                                int(230 + 25 * intensity),
                            )
                        else:
                            color = (
                                int(20 + 30 * intensity),
                                int(95 + 75 * intensity),
                                int(120 + 90 * intensity),
                            )
                        draw.text((column["x"], y), char, font=mono, fill=color)

            # Telemetry waveform.
            points = []
            for x in range(30, width - 30, 6):
                phase = x / 34.0 + t * math.tau * 4.0
                value = (
                    math.sin(phase) * 0.5
                    + math.sin(phase * 2.3 + 1.7) * 0.22
                    + math.sin(phase * 5.1 + t * math.tau) * 0.08
                )
                points.append((x, height - 150 + value * 44))
            draw.line(points, fill=(80, 240, 220), width=2, joint="curve")

            # HUD.
            draw.rectangle((0, 0, width, 44), fill=(4, 9, 16))
            draw.line((0, 44, width, 44), fill=(20, 60, 76), width=1)
            draw.ellipse((18, 17, 26, 25), fill=(255, 92, 92))
            draw.text((36, 12), "LIVE // REPO SIGNAL", font=mono_small, fill=(170, 235, 235))
            draw.text((width - 98, 12), f"00:{frame_index // FPS:02d}:{frame_index % FPS:02d}", font=mono_small, fill=(90, 160, 180))

            draw.text((24, height - 92), "SYMBOLS", font=mono_small, fill=(90, 140, 160))
            draw.text((24, height - 74), f"{1240 + frame_index * 3:04d}", font=mono_big, fill=(210, 255, 250))
            draw.text((width - 190, height - 92), "RELATIONS", font=mono_small, fill=(90, 140, 160))
            draw.text((width - 190, height - 74), f"{4820 + frame_index * 7:04d}", font=mono_big, fill=(180, 150, 255))

            # Scanline + vignette.
            scan_y = int((t * 2.0 % 1.0) * height)
            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            odraw = ImageDraw.Draw(overlay)
            odraw.rectangle((0, scan_y, width, scan_y + 2), fill=(120, 255, 240, 60))
            overlay = overlay.filter(ImageFilter.GaussianBlur(1))
            base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")

            vignette = Image.new("L", (width, height), 0)
            vdraw = ImageDraw.Draw(vignette)
            vdraw.ellipse((-width * 0.35, -height * 0.2, width * 1.35, height * 1.2), fill=255)
            vignette = vignette.filter(ImageFilter.GaussianBlur(120))
            black = Image.new("RGB", (width, height), (0, 0, 0))
            base = Image.composite(base, black, vignette)

            frame = np.asarray(base)
            if frame_index == total // 3:
                poster = frame.copy()
            yield frame

    encode(frames(), (width, height), OUT / "signal.mp4")
    assert poster is not None
    save_poster(poster, OUT / "signal-poster.jpg")


# ---------------------------------------------------------------------------
# 3. ORBITAL — a luminous repo-graph observatory
# ---------------------------------------------------------------------------

def save_orbital() -> None:
    width = height = 640
    total = FPS * 6
    rng = np.random.default_rng(11)
    nodes = []
    for ring in range(3):
        count = 7 + ring * 5
        for index in range(count):
            angle = math.tau * index / count + rng.uniform(-0.12, 0.12)
            radius = 0.26 + ring * 0.17 + rng.uniform(-0.025, 0.025)
            nodes.append(
                {
                    "radius": radius,
                    "angle": angle,
                    "speed": rng.uniform(0.35, 1.0) * (1 if ring % 2 == 0 else -1),
                    "size": rng.uniform(2.0, 4.8),
                    "phase": rng.uniform(0.0, math.tau),
                    "ring": ring,
                }
            )

    poster = None
    def frames():
        nonlocal poster
        for frame_index in range(total):
            t = frame_index / total
            base = Image.new("RGB", (width, height), (2, 4, 10))
            layer = Image.new("RGB", (width, height), (0, 0, 0))
            draw = ImageDraw.Draw(layer)

            cx, cy = width / 2, height / 2
            tilt = 0.36
            points = []
            for node in nodes:
                angle = node["angle"] + t * math.tau * node["speed"]
                radius = node["radius"] * width
                x = cx + math.cos(angle) * radius
                y = cy + math.sin(angle) * radius * tilt
                depth = 0.5 + 0.5 * math.sin(angle + node["phase"])
                points.append((x, y, depth, node))

            # Relationship arcs between nearby ring nodes.
            for i, (x1, y1, d1, n1) in enumerate(points):
                for x2, y2, d2, n2 in points[i + 1 :]:
                    if abs(n1["ring"] - n2["ring"]) == 1 and ((i * 7 + int(n2["angle"] * 10)) % 5 == 0):
                        shade = int(18 + 30 * min(d1, d2))
                        draw.line((x1, y1, x2, y2), fill=(shade, shade + 12, min(90, shade + 46)), width=1)

            # Elliptical orbit guides.
            for ring in range(3):
                radius = (0.26 + ring * 0.17) * width
                box = (cx - radius, cy - radius * tilt, cx + radius, cy + radius * tilt)
                draw.ellipse(box, outline=(14 + ring * 8, 30 + ring * 10, 48 + ring * 14), width=1)

            for x, y, depth, node in points:
                radius = node["size"] * (0.55 + depth * 0.9)
                if node["ring"] == 0:
                    color = (120, 245, 235)
                elif node["ring"] == 1:
                    color = (150, 130, 255)
                else:
                    color = (255, 170, 120)
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)

            layer = layer.filter(ImageFilter.GaussianBlur(0.6))
            glow = layer.filter(ImageFilter.GaussianBlur(9))
            base = Image.blend(base, glow, 0.55)
            base = Image.blend(base, layer, 0.9)
            draw = ImageDraw.Draw(base)

            # Core glow.
            core_radius = 46 + 6 * math.sin(t * math.tau * 2)
            for step in range(7):
                radius = core_radius + step * 9
                alpha = max(0, 40 - step * 5)
                draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(alpha, alpha + 20, alpha + 30), width=2)
            draw.ellipse((cx - 18, cy - 18, cx + 18, cy + 18), fill=(210, 255, 250))
            draw.ellipse((cx - 7, cy - 7, cx + 7, cy + 7), fill=(255, 255, 255))

            # HUD ring ticks.
            for tick in range(48):
                angle = tick / 48 * math.tau + t * 0.25
                r1 = width * 0.462
                r2 = r1 - (6 if tick % 4 == 0 else 3)
                x1 = cx + math.cos(angle) * r1
                y1 = cy + math.sin(angle) * r1 * 0.94
                x2 = cx + math.cos(angle) * r2
                y2 = cy + math.sin(angle) * r2 * 0.94
                draw.line((x1, y1, x2, y2), fill=(40, 80, 96), width=1)

            # Vignette.
            vignette = Image.new("L", (width, height), 0)
            vdraw = ImageDraw.Draw(vignette)
            vdraw.ellipse((-width * 0.2, -height * 0.2, width * 1.2, height * 1.2), fill=255)
            vignette = vignette.filter(ImageFilter.GaussianBlur(100))
            black = Image.new("RGB", (width, height), (0, 0, 0))
            base = Image.composite(base, black, vignette)

            frame = np.asarray(base)
            if frame_index == total // 3:
                poster = frame.copy()
            yield frame

    encode(frames(), (width, height), OUT / "orbital.mp4")
    assert poster is not None
    save_poster(poster, OUT / "orbital-poster.jpg")


def main() -> None:
    print("Rendering nextworld.mp4 ...")
    save_nextworld()
    print("Rendering signal.mp4 ...")
    save_signal()
    print("Rendering orbital.mp4 ...")
    save_orbital()
    for path in sorted(OUT.glob("*")):
        print(f"  {path.name:28s} {path.stat().st_size / 1024:8.1f} KB")


if __name__ == "__main__":
    main()
