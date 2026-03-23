#!/usr/bin/env python3
"""
Video Censor — 录屏视频敏感信息自动脱敏工具

用法:
    python video_censor.py input.mp4
    python video_censor.py input.mp4 -c my_config.yaml
    python video_censor.py input.mp4 -o output.mp4
    python video_censor.py input.mp4 --preview
    python video_censor.py input.mp4 --dry-run
"""

import argparse
import math
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

import cv2
import pytesseract
import yaml


# ────────────────────────────────────────────────────────────
# Data structures
# ────────────────────────────────────────────────────────────

@dataclass
class TextBox:
    """A detected text region in a single frame."""
    x: int
    y: int
    w: int
    h: int
    text: str
    confidence: float
    frame_time: float  # seconds


@dataclass
class CensorRegion:
    """A region to censor across a time span."""
    x: int
    y: int
    w: int
    h: int
    t_start: float
    t_end: float
    matched_text: str
    pattern_name: str


# ────────────────────────────────────────────────────────────
# Config loading
# ────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "patterns": [
        {"name": "手机号", "regex": r"1[3-9]\d{9}"},
        {"name": "身份证号", "regex": r"\d{17}[\dXx]"},
    ],
    "keywords": [],
    "settings": {
        "output_fps": None,
        "sample_fps": None,
        "blur_mode": "gaussian",
        "blur_strength": 30,
        "blur_color": "black",
        "blur_padding": 10,
        "ocr_lang": "chi_sim+eng",
        "confidence_threshold": 40,
        "iou_threshold": 0.5,
    },
}


def load_config(config_path: str | None) -> dict:
    """Load config from YAML file, falling back to defaults."""
    config = DEFAULT_CONFIG.copy()
    if config_path and os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        if "patterns" in user_cfg:
            config["patterns"] = user_cfg["patterns"] or []
        if "keywords" in user_cfg:
            config["keywords"] = user_cfg["keywords"] or []
        if "settings" in user_cfg:
            config["settings"] = {**config["settings"], **(user_cfg["settings"] or {})}
    elif config_path:
        print(f"⚠️  配置文件 {config_path} 不存在，使用默认配置")
    return config


# ────────────────────────────────────────────────────────────
# OCR & detection
# ────────────────────────────────────────────────────────────

def extract_text_boxes(frame, frame_time: float, settings: dict) -> list[TextBox]:
    """Run OCR on a single frame and return detected text boxes."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    ocr_lang = settings.get("ocr_lang", "chi_sim+eng")
    conf_threshold = settings.get("confidence_threshold", 40)

    try:
        data = pytesseract.image_to_data(
            gray,
            lang=ocr_lang,
            output_type=pytesseract.Output.DICT,
            config="--psm 6",
        )
    except pytesseract.TesseractError as e:
        print(f"⚠️  OCR 错误: {e}")
        return []

    boxes = []
    n = len(data["text"])
    for i in range(n):
        text = data["text"][i].strip()
        conf = int(data["conf"][i]) if data["conf"][i] != "-1" else 0
        if not text or conf < conf_threshold:
            continue
        boxes.append(TextBox(
            x=data["left"][i],
            y=data["top"][i],
            w=data["width"][i],
            h=data["height"][i],
            text=text,
            confidence=conf,
            frame_time=frame_time,
        ))
    return boxes


def match_sensitive(boxes: list[TextBox], config: dict) -> list[TextBox]:
    """Filter text boxes that match sensitive patterns or keywords."""
    patterns = config.get("patterns", [])
    keywords = config.get("keywords", [])
    matched = []

    # --- Individual box matching (regex) ---
    compiled_patterns = []
    for p in patterns:
        try:
            compiled_patterns.append((p["name"], re.compile(p["regex"])))
        except re.error as e:
            print(f"⚠️  正则表达式错误 [{p['name']}]: {e}")

    for box in boxes:
        for name, pattern in compiled_patterns:
            if pattern.search(box.text):
                box_copy = TextBox(
                    x=box.x, y=box.y, w=box.w, h=box.h,
                    text=box.text, confidence=box.confidence,
                    frame_time=box.frame_time,
                )
                matched.append(box_copy)
                break

    # --- Keyword matching (concatenate nearby words) ---
    if keywords:
        # Sort boxes by y then x to group text on the same line
        sorted_boxes = sorted(boxes, key=lambda b: (b.y // 20, b.x))

        # Group boxes into lines (boxes within 20px vertical distance)
        lines: list[list[TextBox]] = []
        current_line: list[TextBox] = []
        for box in sorted_boxes:
            if current_line and abs(box.y - current_line[0].y) > 20:
                lines.append(current_line)
                current_line = [box]
            else:
                current_line.append(box)
        if current_line:
            lines.append(current_line)

        # Search keywords in concatenated line text
        for line_boxes in lines:
            line_text = "".join(b.text for b in line_boxes)
            for kw in keywords:
                if kw in line_text:
                    # Find which boxes contribute to the keyword
                    # Simple approach: mark all boxes in the line that overlap
                    # with the keyword's character positions
                    kw_start = line_text.index(kw)
                    kw_end = kw_start + len(kw)
                    char_pos = 0
                    for box in line_boxes:
                        box_start = char_pos
                        box_end = char_pos + len(box.text)
                        if box_start < kw_end and box_end > kw_start:
                            already = any(
                                m.x == box.x and m.y == box.y
                                and m.frame_time == box.frame_time
                                for m in matched
                            )
                            if not already:
                                matched.append(box)
                        char_pos = box_end

    return matched


# ────────────────────────────────────────────────────────────
# Region tracking & merging
# ────────────────────────────────────────────────────────────

def iou(a: dict, b: dict) -> float:
    """Compute Intersection over Union of two rectangles."""
    x1 = max(a["x"], b["x"])
    y1 = max(a["y"], b["y"])
    x2 = min(a["x"] + a["w"], b["x"] + b["w"])
    y2 = min(a["y"] + a["h"], b["y"] + b["h"])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = a["w"] * a["h"]
    area_b = b["w"] * b["h"]
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0


def merge_detections(
    all_matches: list[TextBox], settings: dict, effective_sample_fps: float
) -> list[CensorRegion]:
    """Merge detected text boxes across frames into CensorRegions.

    Only merges spatially overlapping detections in strictly consecutive frames.
    No time buffering — each region covers exactly the frames where it was detected.
    """
    iou_thresh = settings.get("iou_threshold", 0.5)
    # Allow merging only within consecutive frames (1.5x frame interval as tolerance)
    max_gap = 1.5 / effective_sample_fps if effective_sample_fps > 0 else 0.2

    # Sort by time
    all_matches.sort(key=lambda b: b.frame_time)

    regions: list[CensorRegion] = []

    for box in all_matches:
        box_rect = {"x": box.x, "y": box.y, "w": box.w, "h": box.h}
        merged = False
        for region in regions:
            region_rect = {"x": region.x, "y": region.y, "w": region.w, "h": region.h}
            if (
                iou(box_rect, region_rect) >= iou_thresh
                and box.frame_time - region.t_end <= max_gap
            ):
                # Extend this region's time span (no spatial expansion —
                # keep the bounding box stable to avoid drift during scrolling)
                region.t_end = box.frame_time
                merged = True
                break

        if not merged:
            regions.append(CensorRegion(
                x=box.x, y=box.y, w=box.w, h=box.h,
                t_start=box.frame_time,
                t_end=box.frame_time,
                matched_text=box.text,
                pattern_name="",
            ))

    return regions


# ────────────────────────────────────────────────────────────
# ffmpeg filter generation
# ────────────────────────────────────────────────────────────

def build_ffmpeg_filter(
    regions: list[CensorRegion], settings: dict, video_w: int, video_h: int
) -> tuple[str, str]:
    """Build ffmpeg filter to censor all detected regions.

    Returns (filter_string, output_label).
    For solid mode, output_label is empty (use -vf).
    For blur modes, output_label is the last filter_complex label (use -filter_complex).
    """
    blur_mode = settings.get("blur_mode", "gaussian")
    blur_color = settings.get("blur_color", "black")
    blur_strength = settings.get("blur_strength", 30)
    padding = settings.get("blur_padding", 10)

    if not regions:
        return "null", ""

    if blur_mode == "solid":
        parts = []
        for r in regions:
            x = max(0, r.x - padding)
            y = max(0, r.y - padding)
            w = min(r.w + 2 * padding, video_w - x)
            h = min(r.h + 2 * padding, video_h - y)
            t_start = f"{r.t_start:.3f}"
            t_end = f"{r.t_end:.3f}"
            parts.append(
                f"drawbox=x={x}:y={y}:w={w}:h={h}"
                f":color={blur_color}:t=fill"
                f":enable='between(t,{t_start},{t_end})'"
            )
        return ",".join(parts), ""

    # For gaussian / pixelate: build sequential crop→blur→overlay chains
    filter_complex_parts = []
    for i, r in enumerate(regions):
        x = max(0, r.x - padding)
        y = max(0, r.y - padding)
        w = min(r.w + 2 * padding, video_w - x)
        h = min(r.h + 2 * padding, video_h - y)

        # Cap blur radius: ffmpeg boxblur requires radius <= min(w,h)/2
        # For YUV420, chroma plane is half the size, so cap chroma radius separately
        max_luma_r = min(w, h) // 2 - 1
        luma_r = max(1, min(blur_strength, max_luma_r))
        max_chroma_r = min(w, h) // 4 - 1  # chroma is subsampled 2x
        chroma_r = max(1, min(blur_strength, max_chroma_r))

        t_start = f"{r.t_start:.3f}"
        t_end = f"{r.t_end:.3f}"
        enable = f"between(t\\,{t_start}\\,{t_end})"

        src = f"[base{i}]" if i > 0 else "[0:v]"
        out_label = f"[base{i+1}]"

        filter_complex_parts.append(
            f"{src}split[main{i}][copy{i}];"
            f"[copy{i}]crop={w}:{h}:{x}:{y},"
            f"boxblur={luma_r}:1:{chroma_r}:1[blurred{i}];"
            f"[main{i}][blurred{i}]overlay={x}:{y}"
            f":enable='{enable}'{out_label}"
        )

    last_label = f"[base{len(regions)}]"
    return ";".join(filter_complex_parts), last_label


# ────────────────────────────────────────────────────────────
# Preview mode: draw red rectangles around detections
# ────────────────────────────────────────────────────────────

def generate_preview(
    input_path: str, output_path: str, regions: list[CensorRegion],
    settings: dict, video_w: int, video_h: int
):
    """Generate a preview video with red boxes drawn around detected regions."""
    padding = settings.get("blur_padding", 10)
    parts = []
    for r in regions:
        x = max(0, r.x - padding)
        y = max(0, r.y - padding)
        w = min(r.w + 2 * padding, video_w - x)
        h = min(r.h + 2 * padding, video_h - y)
        t_start = f"{r.t_start:.3f}"
        t_end = f"{r.t_end:.3f}"
        parts.append(
            f"drawbox=x={x}:y={y}:w={w}:h={h}"
            f":color=red:t=3"
            f":enable='between(t,{t_start},{t_end})'"
        )

    if not parts:
        print("ℹ️  没有检测到需要脱敏的区域")
        return

    vf = ",".join(parts)
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", vf,
        "-c:a", "copy",
        output_path,
    ]
    print(f"\n🔍 生成预览视频: {output_path}")
    print(f"   ffmpeg 命令: {' '.join(cmd)}\n")
    subprocess.run(cmd, check=True)
    print(f"\n✅ 预览视频已生成: {output_path}")


# ────────────────────────────────────────────────────────────
# Video pre-processing (fps reduction)
# ────────────────────────────────────────────────────────────

def preprocess_video_fps(input_path: str, target_fps: float, original_fps: float) -> str | None:
    """Pre-process video to lower fps using ffmpeg. Returns temp file path, or None if not needed."""
    if target_fps >= original_fps:
        return None

    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp_path = tmp.name
    tmp.close()

    print(f"\n⏬ 预处理: 将视频从 {original_fps:.1f}fps 降至 {target_fps}fps...")
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-filter:v", f"fps=fps={target_fps}",
        "-c:a", "copy",
        tmp_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"   预处理完成: {tmp_path}")
        return tmp_path
    except subprocess.CalledProcessError as e:
        print(f"⚠️  预处理失败: {e.stderr.decode() if e.stderr else e}")
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return None


# ────────────────────────────────────────────────────────────
# Main processing pipeline
# ────────────────────────────────────────────────────────────

def process_video(
    input_path: str,
    output_path: str,
    config: dict,
    preview: bool = False,
    dry_run: bool = False,
):
    """Main pipeline: sample frames → OCR → match → blur → output."""
    settings = config["settings"]
    output_fps = settings.get("output_fps")
    sample_fps = settings.get("sample_fps")

    # Open video to get original properties
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print(f"❌ 无法打开视频: {input_path}")
        sys.exit(1)

    original_fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    video_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = total_frames / original_fps if original_fps > 0 else 0
    cap.release()

    print(f"📹 视频信息: {video_w}x{video_h}, {original_fps:.1f}fps, "
          f"{total_frames}帧, 时长 {duration:.1f}秒")

    # Determine effective output_fps and sample_fps
    effective_output_fps = output_fps if output_fps and output_fps < original_fps else original_fps
    # sample_fps defaults to output_fps when not explicitly set
    if sample_fps:
        effective_sample_fps = sample_fps
    else:
        effective_sample_fps = effective_output_fps

    # Pre-process: reduce fps if output_fps < original_fps
    preprocessed_path = None
    analysis_input = input_path
    if effective_output_fps < original_fps:
        preprocessed_path = preprocess_video_fps(input_path, effective_output_fps, original_fps)
        if preprocessed_path:
            analysis_input = preprocessed_path

    # Open the (possibly pre-processed) video for OCR analysis
    cap = cv2.VideoCapture(analysis_input)
    if not cap.isOpened():
        print(f"❌ 无法打开视频: {analysis_input}")
        sys.exit(1)

    video_fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Calculate frame interval for sampling
    frame_interval = max(1, int(video_fps / effective_sample_fps))
    analyze_every_frame = frame_interval == 1

    if analyze_every_frame:
        print(f"⚙️  输出帧率: {effective_output_fps}fps | 采样: 每帧都分析 → 预计 {total_frames} 帧")
    else:
        print(f"⚙️  输出帧率: {effective_output_fps}fps | 采样率: {effective_sample_fps}fps → "
              f"预计分析 {int(duration * effective_sample_fps)} 帧")

    all_matches: list[TextBox] = []
    frames_analyzed = 0

    print(f"\n🔎 开始 OCR 分析...")
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_interval == 0:
            frame_time = frame_idx / video_fps
            boxes = extract_text_boxes(frame, frame_time, settings)
            sensitive = match_sensitive(boxes, config)
            if sensitive:
                all_matches.extend(sensitive)
                texts = ", ".join(f'"{b.text}"' for b in sensitive)
                print(f"   ⏱️  {frame_time:6.1f}s | 发现 {len(sensitive)} 处敏感信息: {texts}")
            frames_analyzed += 1

            # Progress indicator every 10 analyzed frames
            if frames_analyzed % 10 == 0:
                pct = frame_idx / total_frames * 100
                print(f"   📊 进度: {pct:.0f}% ({frames_analyzed} 帧已分析)")

        frame_idx += 1

    cap.release()

    print(f"\n📊 分析完成: 共分析 {frames_analyzed} 帧，"
          f"发现 {len(all_matches)} 处敏感信息匹配")

    if not all_matches:
        print("✅ 未发现需要脱敏的信息。")
        _cleanup_temp(preprocessed_path)
        return

    # Merge detections into regions
    regions = merge_detections(all_matches, settings, effective_sample_fps)
    print(f"📦 合并为 {len(regions)} 个脱敏区域:")
    for i, r in enumerate(regions):
        print(f"   [{i+1}] ({r.x},{r.y}) {r.w}x{r.h} | "
              f"{r.t_start:.1f}s - {r.t_end:.1f}s | "
              f'文字: "{r.matched_text}"')

    if dry_run:
        print("\n🏁 Dry-run 模式，不生成输出文件。")
        _cleanup_temp(preprocessed_path)
        return

    # Use pre-processed video as ffmpeg input (already at target fps)
    ffmpeg_input = analysis_input

    if preview:
        preview_path = output_path.replace(".mp4", "_preview.mp4")
        if preview_path == output_path:
            preview_path = output_path.rsplit(".", 1)[0] + "_preview.mp4"
        generate_preview(ffmpeg_input, preview_path, regions, settings, video_w, video_h)
        _cleanup_temp(preprocessed_path)
        return

    # Build ffmpeg command
    blur_mode = settings.get("blur_mode", "gaussian")

    if blur_mode == "solid":
        vf_filter, _ = build_ffmpeg_filter(
            regions, settings, video_w, video_h
        )
        cmd = [
            "ffmpeg", "-y", "-i", ffmpeg_input,
            "-vf", vf_filter,
            "-c:a", "copy",
            output_path,
        ]
    else:
        filter_complex, last_label = build_ffmpeg_filter(
            regions, settings, video_w, video_h
        )
        cmd = [
            "ffmpeg", "-y", "-i", ffmpeg_input,
            "-filter_complex", filter_complex,
            "-map", last_label,
            "-map", "0:a?",
            "-c:a", "copy",
            output_path,
        ]

    print(f"\n🎬 开始生成脱敏视频: {output_path}")
    print(f"   模糊模式: {blur_mode}")

    # Write the ffmpeg command to a temp script for debugging
    cmd_str = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    print(f"   ffmpeg 命令:\n   {cmd_str}\n")

    try:
        subprocess.run(cmd, check=True)
        print(f"\n✅ 脱敏视频已生成: {output_path}")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ ffmpeg 处理失败 (exit code {e.returncode})")
        print("   提示: 可以尝试使用 --preview 模式先检查检测区域是否正确")
        _cleanup_temp(preprocessed_path)
        sys.exit(1)

    _cleanup_temp(preprocessed_path)


def _cleanup_temp(path: str | None):
    """Remove temporary file if it exists."""
    if path and os.path.exists(path):
        os.unlink(path)


# ────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="录屏视频敏感信息自动脱敏工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python video_censor.py input.mp4                     使用默认配置
  python video_censor.py input.mp4 -c config.yaml      指定配置文件
  python video_censor.py input.mp4 -o output.mp4       指定输出文件
  python video_censor.py input.mp4 --preview           生成预览视频(红框标注)
  python video_censor.py input.mp4 --dry-run           仅检测输出，不处理
        """,
    )
    parser.add_argument("input", help="输入视频文件路径")
    parser.add_argument("-c", "--config", default="censor_config.yaml",
                        help="配置文件路径 (默认: censor_config.yaml)")
    parser.add_argument("-o", "--output", default=None,
                        help="输出视频文件路径 (默认: input_censored.mp4)")
    parser.add_argument("--preview", action="store_true",
                        help="预览模式: 生成红框标注视频，不做模糊处理")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅检测并输出敏感信息，不生成视频")

    args = parser.parse_args()

    # Validate input
    if not os.path.exists(args.input):
        print(f"❌ 输入文件不存在: {args.input}")
        sys.exit(1)

    # Determine output path (default: same directory as input file)
    if args.output:
        output_path = args.output
    else:
        input_abs = os.path.abspath(args.input)
        base, ext = os.path.splitext(input_abs)
        output_path = f"{base}_censored{ext}"

    # Load config
    config = load_config(args.config)

    print("=" * 60)
    print("🔒 Video Censor — 录屏视频敏感信息自动脱敏")
    print("=" * 60)
    print(f"📂 输入: {args.input}")
    if not args.dry_run:
        print(f"📂 输出: {output_path}")
    print(f"📋 配置: {args.config}")
    print(f"🔍 正则模式: {len(config.get('patterns', []))} 个")
    print(f"🔑 关键词: {len(config.get('keywords', []))} 个")
    out_fps = config['settings'].get('output_fps')
    print(f"🎞️  输出帧率: {out_fps if out_fps else '保持原始'}")
    print(f"🌫️  模糊模式: {config['settings'].get('blur_mode', 'gaussian')}")
    print()

    process_video(
        input_path=args.input,
        output_path=output_path,
        config=config,
        preview=args.preview,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
