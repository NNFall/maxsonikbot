from __future__ import annotations

from pathlib import Path
import subprocess
import logging

logger = logging.getLogger(__name__)


def check_ffmpeg(ffmpeg_path: str = 'ffmpeg') -> bool:
    try:
        result = subprocess.run([ffmpeg_path, '-version'], capture_output=True, text=True)
    except FileNotFoundError:
        return False
    except Exception:
        return False
    return result.returncode == 0


def concat_videos(video_paths: list[str], output_path: str, ffmpeg_path: str = 'ffmpeg') -> None:
    if len(video_paths) < 2:
        raise ValueError('Need at least two videos to concat')

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    logger.info('FFmpeg concat start output=%s', out)

    list_file = out.with_suffix('.txt')
    try:
        with list_file.open('w', encoding='utf-8') as f:
            for path in video_paths:
                p = Path(path).resolve().as_posix()
                f.write(f"file '{p}'\n")

        logger.info('FFmpeg concat list=%s', list_file)

        cmd = [
            ffmpeg_path,
            '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', str(list_file.resolve()),
            '-c', 'copy',
            str(out.resolve()),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error('FFmpeg concat failed: %s', result.stderr or 'unknown error')
            raise RuntimeError(result.stderr or 'ffmpeg concat failed')
        logger.info('FFmpeg concat success output=%s', out)
    finally:
        try:
            list_file.unlink(missing_ok=True)
        except Exception:
            pass


def remove_fragment(
    input_path: str,
    start_sec: float,
    end_sec: float,
    output_path: str,
    ffmpeg_path: str = 'ffmpeg',
) -> None:
    if start_sec < 0 or end_sec < 0 or end_sec <= start_sec:
        raise ValueError('Invalid time range')

    inp = Path(input_path).resolve()
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    logger.info('FFmpeg cut start input=%s start=%s end=%s', inp, start_sec, end_sec)

    # Use re-encode + concat filter to avoid broken timestamps/freezes
    filter_with_audio = (
        f"[0:v]trim=0:{start_sec},setpts=PTS-STARTPTS[v0];"
        f"[0:a]atrim=0:{start_sec},asetpts=PTS-STARTPTS[a0];"
        f"[0:v]trim={end_sec}:,setpts=PTS-STARTPTS[v1];"
        f"[0:a]atrim={end_sec}:,asetpts=PTS-STARTPTS[a1];"
        f"[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]"
    )

    cmd = [
        ffmpeg_path,
        '-y',
        '-i', str(inp),
        '-filter_complex', filter_with_audio,
        '-map', '[v]',
        '-map', '[a]',
        '-c:v', 'libx264',
        '-preset', 'veryfast',
        '-crf', '23',
        '-c:a', 'aac',
        '-movflags', '+faststart',
        str(out),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning('FFmpeg cut with audio failed: %s', result.stderr or 'unknown error')
        # Retry without audio if input has no audio stream
        filter_no_audio = (
            f"[0:v]trim=0:{start_sec},setpts=PTS-STARTPTS[v0];"
            f"[0:v]trim={end_sec}:,setpts=PTS-STARTPTS[v1];"
            f"[v0][v1]concat=n=2:v=1:a=0[v]"
        )
        cmd2 = [
            ffmpeg_path,
            '-y',
            '-i', str(inp),
            '-filter_complex', filter_no_audio,
            '-map', '[v]',
            '-c:v', 'libx264',
            '-preset', 'veryfast',
            '-crf', '23',
            '-movflags', '+faststart',
            str(out),
        ]
        result2 = subprocess.run(cmd2, capture_output=True, text=True)
        if result2.returncode != 0:
            logger.error('FFmpeg cut failed: %s', result2.stderr or 'unknown error')
            raise RuntimeError(result2.stderr or 'ffmpeg cut failed')

    logger.info('FFmpeg cut success output=%s', out)
