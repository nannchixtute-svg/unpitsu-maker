#!/usr/bin/env python3
"""動画から場面転換ごとにスクリーンショットを抽出し、PDFにまとめるCLIツール。

外部APIやAI課金サービスは使用せず、ffmpegによるローカル処理のみで完結する。

使い方:
    python extract_scenes.py --input video.mp4 --output result.pdf --threshold 0.3
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

logger = logging.getLogger("extract_scenes")

DEFAULT_THRESHOLD = 0.3
DEFAULT_IMAGE_FORMAT = "jpg"
DEFAULT_IMAGES_PER_PAGE = 1


@dataclass
class SceneFrame:
    index: int
    timestamp: float
    image_path: Path


def check_dependencies() -> None:
    """ffmpeg / ffprobe がインストールされているか確認する。"""
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise EnvironmentError(
                f"'{tool}' が見つかりません。ffmpegをインストールしてください "
                "(例: 'brew install ffmpeg' / 'sudo apt install ffmpeg')。"
            )


def validate_input(video_path: Path) -> None:
    """入力動画ファイルの存在チェック。"""
    if not video_path.exists():
        raise FileNotFoundError(f"動画ファイルが見つかりません: {video_path}")
    if not video_path.is_file():
        raise ValueError(f"指定されたパスはファイルではありません: {video_path}")


def get_video_duration(video_path: Path) -> float:
    """ffprobeで動画の長さ（秒）を取得する。"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"動画の長さを取得できませんでした: {result.stderr.strip()}")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"動画の長さの解析に失敗しました: {result.stdout!r}") from exc


def format_timestamp(seconds: float) -> str:
    """秒数を hh:mm:ss 形式に変換する。"""
    total_seconds = int(round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_timestamp_for_filename(seconds: float) -> str:
    """秒数をファイル名に使える hh-mm-ss 形式に変換する。"""
    return format_timestamp(seconds).replace(":", "-")


def detect_scene_timestamps(
    video_path: Path, threshold: float, min_gap: float = 1.0
) -> list[float]:
    """ffmpegのシーン検出フィルタで場面転換タイムスタンプ一覧を取得する。

    先頭フレーム(0.0秒)は常にシーン1として含める。
    min_gap未満の間隔で連続検出されたタイムスタンプは重複とみなし間引く。
    """
    filter_expr = f"select='gt(scene,{threshold})',showinfo"
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", filter_expr,
        "-f", "null", "-",
    ]
    logger.debug("実行コマンド: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    pts_pattern = re.compile(r"pts_time:([0-9]+\.?[0-9]*)")
    timestamps = [0.0]
    for match in pts_pattern.finditer(result.stderr):
        timestamps.append(float(match.group(1)))

    timestamps = sorted(set(timestamps))

    filtered = [timestamps[0]]
    for ts in timestamps[1:]:
        if ts - filtered[-1] >= min_gap:
            filtered.append(ts)

    return filtered


def evaluate_scene_count(num_scenes: int, duration_seconds: float, threshold: float) -> None:
    """検出されたシーン数が妥当な範囲か目安をログに出す。"""
    if duration_seconds <= 0:
        return
    scenes_per_minute = num_scenes / (duration_seconds / 60)
    logger.info(
        "検出シーン数: %d (動画長: %s, 閾値: %.2f, 1分あたり約%.1fシーン)",
        num_scenes, format_timestamp(duration_seconds), threshold, scenes_per_minute,
    )
    if scenes_per_minute < 0.5:
        logger.warning(
            "シーン数が少なすぎる可能性があります。--threshold を下げて再実行することを検討してください "
            "(例: %.2f)", max(threshold - 0.1, 0.05),
        )
    elif scenes_per_minute > 10:
        logger.warning(
            "シーン数が多すぎる可能性があります。--threshold を上げて再実行することを検討してください "
            "(例: %.2f)", threshold + 0.1,
        )
    else:
        logger.info("シーン数は妥当な範囲です。")


def extract_frame(video_path: Path, timestamp: float, output_path: Path) -> None:
    """指定タイムスタンプのフレームを静止画として保存する。

    高速シークと精密シークを組み合わせ、速度と精度を両立させる。
    """
    fast_seek = max(timestamp - 2.0, 0.0)
    precise_offset = timestamp - fast_seek
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{fast_seek:.3f}",
        "-i", str(video_path),
        "-ss", f"{precise_offset:.3f}",
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not output_path.exists():
        raise RuntimeError(
            f"フレーム抽出に失敗しました (t={timestamp:.2f}s): {result.stderr.strip()}"
        )


def extract_all_frames(
    video_path: Path,
    timestamps: list[float],
    output_dir: Path,
    image_format: str,
) -> list[SceneFrame]:
    """検出された全タイムスタンプのフレームを抽出する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    frames: list[SceneFrame] = []
    for index, timestamp in enumerate(timestamps, start=1):
        filename = f"scene_{index:03d}_{format_timestamp_for_filename(timestamp)}.{image_format}"
        output_path = output_dir / filename
        logger.info("フレーム抽出中 [%d/%d] t=%s -> %s",
                    index, len(timestamps), format_timestamp(timestamp), filename)
        extract_frame(video_path, timestamp, output_path)
        frames.append(SceneFrame(index=index, timestamp=timestamp, image_path=output_path))
    return frames


def build_pdf(
    frames: list[SceneFrame],
    output_pdf: Path,
    images_per_page: int,
    video_path: Path,
) -> None:
    """抽出したフレーム一覧をタイムスタンプ付きPDFにまとめる。"""
    page_width, page_height = A4
    margin = 15 * mm
    caption_height = 10 * mm

    c = canvas.Canvas(str(output_pdf), pagesize=A4)

    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin, page_height - margin, "シーン抽出結果")
    c.setFont("Helvetica", 10)
    c.drawString(margin, page_height - margin - 16, f"元動画: {video_path.name}")
    c.drawString(margin, page_height - margin - 30, f"検出シーン数: {len(frames)}")
    c.showPage()

    chunks = [frames[i:i + images_per_page] for i in range(0, len(frames), images_per_page)]

    for chunk in chunks:
        rows = len(chunk)
        cell_height = (page_height - 2 * margin) / rows
        for row_index, frame in enumerate(chunk):
            cell_top = page_height - margin - row_index * cell_height
            image_area_height = cell_height - caption_height
            image_area_width = page_width - 2 * margin

            reader = ImageReader(str(frame.image_path))
            img_width, img_height = reader.getSize()
            scale = min(image_area_width / img_width, image_area_height / img_height)
            draw_width = img_width * scale
            draw_height = img_height * scale
            draw_x = margin + (image_area_width - draw_width) / 2
            draw_y = cell_top - image_area_height + (image_area_height - draw_height) / 2

            c.drawImage(
                reader, draw_x, draw_y, width=draw_width, height=draw_height,
                preserveAspectRatio=True, anchor="c",
            )

            caption = f"シーン {frame.index:03d}  /  {format_timestamp(frame.timestamp)}"
            c.setFont("Helvetica", 11)
            c.drawCentredString(
                page_width / 2, cell_top - image_area_height - 7 * mm, caption,
            )
        c.showPage()

    c.save()
    logger.info("PDFを生成しました: %s", output_pdf)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="動画から場面転換ごとにスクリーンショットを抽出し、タイムスタンプ付きPDFにまとめる。",
    )
    parser.add_argument("--input", "-i", required=True, type=Path, help="入力動画ファイルのパス")
    parser.add_argument("--output", "-o", default=Path("scenes.pdf"), type=Path, help="出力PDFのパス (デフォルト: scenes.pdf)")
    parser.add_argument("--threshold", "-t", default=DEFAULT_THRESHOLD, type=float,
                         help=f"シーン検出感度の閾値。0.0〜1.0で小さいほど敏感 (デフォルト: {DEFAULT_THRESHOLD})")
    parser.add_argument("--min-gap", default=1.0, type=float,
                         help="連続する検出結果を重複とみなす最小間隔秒 (デフォルト: 1.0)")
    parser.add_argument("--format", choices=["jpg", "png"], default=DEFAULT_IMAGE_FORMAT,
                         help=f"抽出する静止画の形式 (デフォルト: {DEFAULT_IMAGE_FORMAT})")
    parser.add_argument("--images-per-page", default=DEFAULT_IMAGES_PER_PAGE, type=int,
                         help=f"1ページに配置するシーン数 (デフォルト: {DEFAULT_IMAGES_PER_PAGE})")
    parser.add_argument("--keep-frames", type=Path, default=None,
                         help="抽出した静止画を保存するディレクトリ (指定しない場合は一時フォルダを使い処理後に削除)")
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログを出力する")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        check_dependencies()
        validate_input(args.input)

        duration = get_video_duration(args.input)

        logger.info("シーン検出を開始します (閾値=%.2f)", args.threshold)
        timestamps = detect_scene_timestamps(args.input, args.threshold, args.min_gap)
        evaluate_scene_count(len(timestamps), duration, args.threshold)

        if args.keep_frames:
            frames_dir = args.keep_frames
            frames_dir.mkdir(parents=True, exist_ok=True)
            frames = extract_all_frames(args.input, timestamps, frames_dir, args.format)
            build_pdf(frames, args.output, args.images_per_page, args.input)
            logger.info("抽出した静止画を保持しました: %s", frames_dir)
        else:
            with tempfile.TemporaryDirectory(prefix="extract_scenes_") as tmp_dir:
                frames = extract_all_frames(args.input, timestamps, Path(tmp_dir), args.format)
                build_pdf(frames, args.output, args.images_per_page, args.input)

        return 0

    except (FileNotFoundError, ValueError, EnvironmentError, RuntimeError) as exc:
        logger.error(str(exc))
        return 1
    except KeyboardInterrupt:
        logger.warning("中断されました。")
        return 130


if __name__ == "__main__":
    sys.exit(main())
