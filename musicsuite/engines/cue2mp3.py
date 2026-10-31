"""Конвертер FLAC/APE + CUE -> MP3 (логика cue2mp3.py без изменений).

Нарезает аудио (FLAC/APE) по временным меткам из CUE, кодирует в MP3,
прописывает ID3v2.4 теги (UTF-8) и встраивает обложку.
"""

import os
import re
import sys
import shutil
import subprocess
import urllib.request
import argparse
import tarfile
from pathlib import Path
from zipfile import ZipFile

from mutagen.mp3 import MP3
from mutagen.id3 import TIT2, TPE1, TALB, TDRC, TCON, TRCK, APIC
from mutagen.flac import FLAC
from mutagen.apev2 import APEv2

from ..progress import as_progress
from ..subproc import run as run_process

_ACTIVE_PROGRESS = None


# ---------------------------------------------------------------------------
# Качество MP3
# ---------------------------------------------------------------------------

# Понятные подписи вместо «v0» и «320». Ключ — то, что видит пользователь,
# значение — (режим, параметр): ("vbr", 0) → LAME VBR V0.
QUALITY_PRESETS = {
    "VBR V0 — максимум, ~245 kbps": ("vbr", 0),
    "VBR V1 — очень высокое, ~225 kbps": ("vbr", 1),
    "VBR V2 — оптимальное, ~190 kbps": ("vbr", 2),
    "VBR V3 — хорошее, ~175 kbps": ("vbr", 3),
    "VBR V4 — среднее, ~165 kbps": ("vbr", 4),
    "VBR V5 — ниже среднего, ~130 kbps": ("vbr", 5),
    "VBR V6 — низкое, ~115 kbps": ("vbr", 6),
    "VBR V8 — очень низкое, ~85 kbps": ("vbr", 8),
    "CBR 320 kbps — максимум": ("cbr", 320),
    "CBR 256 kbps — очень высокое": ("cbr", 256),
    "CBR 224 kbps — высокое": ("cbr", 224),
    "CBR 192 kbps — стандарт": ("cbr", 192),
    "CBR 160 kbps — среднее": ("cbr", 160),
    "CBR 128 kbps — экономное": ("cbr", 128),
    "CBR 96 kbps — минимальное": ("cbr", 96),
}

DEFAULT_QUALITY = "VBR V0 — максимум, ~245 kbps"

# Старые значения CLI: принимаем, чтобы не ломать скрипты пользователей.
_LEGACY_QUALITY = {
    "v0": "VBR V0 — максимум, ~245 kbps",
    "320": "CBR 320 kbps — максимум",
}


def encode_args(quality: str):
    """Аргументы FFmpeg для выбранного качества.

    Понимает и новые подписи, и старые «v0»/«320». Неизвестное значение
    заменяется на значение по умолчанию — лучше собрать альбом в обычном
    качестве, чем упасть на опечатке.
    """
    key = _LEGACY_QUALITY.get(quality, quality)
    mode, value = QUALITY_PRESETS.get(
        key, QUALITY_PRESETS[DEFAULT_QUALITY]
    )

    if mode == "vbr":
        return ["-c:a", "libmp3lame", "-q:a", str(value)]
    return ["-c:a", "libmp3lame", "-b:a", f"{value}k"]


def create_parser():
    parser = argparse.ArgumentParser(
        description="Конвертер FLAC/APE+CUE -> MP3 с тегами ID3v2.4 и обложкой.",
        epilog="Примеры:\n"
               "  python cue2mp3.py -i release.cue\n"
               "  python cue2mp3.py -i \"D:\\Music\\Album\" -o ./mp3 -q 320"
    )
    parser.add_argument("-i", "--input", required=True,
                        help="Путь к .cue файлу или папке с альбомом")
    parser.add_argument("-o", "--output", default="mp3_output",
                        help="Папка вывода (по умолчанию: mp3_output)")
    parser.add_argument("-q", "--quality", default=DEFAULT_QUALITY,
                        choices=list(QUALITY_PRESETS) + list(_LEGACY_QUALITY),
                        help="Качество MP3: VBR V0…V8 или CBR 320…96")
    parser.add_argument("--cover", default="",
                        help="Ссылка на обложку (http/https) для встраивания в теги")
    parser.add_argument("--debug", action="store_true", help="Включить отладочный вывод")
    return parser


def resolve_ffmpeg(progress=None):
    report = as_progress(progress)
    ff = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if ff:
        report.message("FFmpeg найден в системе")
        return str(Path(ff).resolve())

    local_dir = Path("ffmpeg_bin")
    ff_local = local_dir / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if ff_local.exists():
        report.message("Используется портативный FFmpeg")
        return str(ff_local.resolve())

    print("[INFO] FFmpeg не найден. Загрузка портативной версии...")
    report.message("Загрузка портативного FFmpeg")
    local_dir.mkdir(exist_ok=True)

    try:
        if sys.platform == "win32":
            url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
            _download_and_extract_zip(url, local_dir, report)
        elif sys.platform == "darwin":
            url = "https://evermeet.cx/ffmpeg/ffmpeg-12.1.2.zip"
            _download_and_extract_zip(url, local_dir, report)
        else:
            url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
            _download_and_extract_tarxz(url, local_dir, report)
    except Exception as e:
        sys.exit(f"[ERROR] Не удалось загрузить FFmpeg: {e}")

    report.message("Распаковка FFmpeg")
    for root, _, files in os.walk(local_dir):
        for f in files:
            if f.startswith("ffmpeg") and not f.endswith((".md", ".txt", ".zip", ".xz")):
                src = Path(root) / f
                shutil.move(str(src), str(ff_local))
                print(f"[INFO] FFmpeg готов: {ff_local}")
                return str(ff_local.resolve())

    sys.exit("[ERROR] Исполняемый файл FFmpeg не найден после распаковки.")


def _report_download(count, block_size, total_size, report):
    """Колбэк urlretrieve: проценты загрузки идут и в консоль, и в прогресс."""
    if total_size <= 0:
        return
    downloaded = count * block_size
    percent = min(100, int(downloaded * 100 / total_size))
    sys.stdout.write(f"\r[INFO] Загрузка FFmpeg: {percent}%")
    sys.stdout.flush()
    report.detail(f"Загрузка FFmpeg: {percent}%")
    if percent >= 100:
        sys.stdout.write("\n")


def _download_and_extract_zip(url, dest_dir, progress=None):
    report = as_progress(progress)
    archive_path = dest_dir / "temp.zip"
    print(f"[INFO] Загрузка: {url}")
    print(f"[INFO] Архив сохраняется в: {archive_path}")
    urllib.request.urlretrieve(
        url, archive_path,
        reporthook=lambda c, b, t: _report_download(c, b, t, report),
    )
    print("[INFO] Распаковка архива...")
    with ZipFile(archive_path, "r") as z:
        z.extractall(dest_dir)
    archive_path.unlink()
    print("[INFO] Распаковка завершена.")


def _download_and_extract_tarxz(url, dest_dir, progress=None):
    report = as_progress(progress)
    archive_path = dest_dir / "temp.tar.xz"
    print(f"[INFO] Загрузка: {url}")
    print(f"[INFO] Архив сохраняется в: {archive_path}")
    urllib.request.urlretrieve(
        url, archive_path,
        reporthook=lambda c, b, t: _report_download(c, b, t, report),
    )
    print("[INFO] Распаковка архива...")
    with tarfile.open(archive_path, "r:xz") as t:
        t.extractall(dest_dir)
    archive_path.unlink()
    print("[INFO] Распаковка завершена.")


def read_cue_file(cue_path: Path):
    for enc in ["utf-8-sig", "utf-8", "cp1251", "iso-8859-1", "windows-1251"]:
        try:
            with open(cue_path, "r", encoding=enc) as f:
                content = f.read()
            if "FILE" in content.upper() and "TRACK" in content.upper():
                return content, enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    sys.exit("[ERROR] Не удалось прочитать CUE файл в поддерживаемой кодировке.")


def parse_cue_content(content: str):
    album_meta = {}
    tracks = []
    current_track = None

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(";") or line.upper().startswith("REM"):
            continue

        m = re.match(r'(PERFORMER|TITLE|DATE|GENRE)\s+"(.*)"', line, re.IGNORECASE)
        if m:
            key, val = m.group(1).upper(), m.group(2)
            if current_track is None:
                album_meta[key] = val
            else:
                current_track[key] = val
            continue

        m = re.match(r'FILE\s+"(.+)"', line, re.IGNORECASE)
        if m:
            album_meta["SOURCE_FILE"] = m.group(1)
            continue

        m = re.match(r'TRACK\s+(\d+)\s+AUDIO', line, re.IGNORECASE)
        if m:
            if current_track:
                tracks.append(current_track)
            current_track = {"NUM": int(m.group(1))}
            continue

        m = re.match(r'INDEX\s+01\s+(.+)', line)
        if m:
            if current_track:
                current_track["TIME"] = m.group(1).strip()

    if current_track:
        tracks.append(current_track)

    for t in tracks:
        t.setdefault("TITLE", album_meta.get("TITLE", "Unknown Track"))
        t.setdefault("PERFORMER", album_meta.get("PERFORMER", "Unknown Artist"))
        t.setdefault("NUM", tracks.index(t) + 1)

    return album_meta, tracks


def time_to_seconds(time_str: str) -> float:
    m = re.match(r'(\d+):(\d+):(\d+)', time_str)
    if not m:
        return 0.0
    minutes, seconds, frames = map(int, m.groups())
    return minutes * 60 + seconds + frames / 75.0


def extract_cover(audio_path: Path, base_dir: Path):
    """Пытается извлечь обложку из тегов (FLAC/APE) или найти в папке."""
    # 1. Проверка встроенных тегов
    try:
        suffix = audio_path.suffix.lower()
        if suffix == ".flac":
            audio = FLAC(audio_path)
            if audio.pictures:
                return audio.pictures[0].data
        elif suffix == ".ape":
            audio = APEv2(audio_path)
            # В APE обложка часто лежит в поле 'Cover Art (Front)' или просто 'Cover Art'
            for key in audio.keys():
                if "Cover Art" in key:
                    return audio[key].value
    except Exception:
        pass

    # 2. Поиск внешнего файла
    for fname in ["cover.jpg", "folder.jpg", "cover.png", "front.jpg", "albumart.jpg"]:
        for f in base_dir.glob("*"):
            if f.name.lower() == fname:
                return f.read_bytes()
    return None


def download_cover(url: str):
    """Скачивает обложку по ссылке. Возвращает (bytes, mime) или (None, None).

    Ошибки не пробрасываем: недоступная картинка не должна срывать
    конвертацию всего альбома — просто останемся без обложки.
    """
    url = (url or "").strip()
    if not url:
        return None, None

    if not url.lower().startswith(("http://", "https://")):
        print(f"[WARN] Ссылка на обложку должна начинаться с http:// или "
              f"https://, получено: {url}")
        return None, None

    print(f"[INFO] Загрузка обложки: {url}")
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (MusEdit)"}
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read()

        if not data:
            print("[WARN] Обложка пустая, пропускаю.")
            return None, None

        # Проверяем, что это действительно картинка, а не HTML-страница
        mime = get_mime_type(data)
        if not (data.startswith(b"\xff\xd8\xff")
                or data.startswith(b"\x89PNG\r\n\x1a\n")
                or data.startswith(b"GIF8")
                or data[:4] == b"RIFF"):
            print("[WARN] По ссылке не картинка (JPEG/PNG/GIF/WEBP), "
                  "обложка не встроена.")
            return None, None

        size_kb = round(len(data) / 1024, 1)
        print(f"[INFO] Обложка загружена: {size_kb} КБ, {mime}")
        return data, mime
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Не удалось загрузить обложку: {exc}")
        return None, None


def get_mime_type(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return "image/jpeg"


def main(args=None, progress=None):
    if args is None:
        parser = create_parser()
        args = parser.parse_args()

    report = as_progress(progress)
    report.start(0, "Подготовка")

    cue_path = Path(args.input).resolve()
    if not cue_path.exists():
        print(f"[ERROR] Указанный путь не существует: {cue_path}")
        return

    if cue_path.is_dir():
        cue_files = list(cue_path.glob("*.cue"))
        if not cue_files:
            print(f"[ERROR] В папке не найден .cue файл: {cue_path}")
            return
        cue_path = cue_files[0]
        print(f"[INFO] Найден CUE файл: {cue_path.name}")

    report.message("Чтение CUE")
    cue_content, detected_enc = read_cue_file(cue_path)
    album_meta, tracks = parse_cue_content(cue_content)
    cue_dir = cue_path.parent

    source_name = album_meta.get("SOURCE_FILE", "")
    source_path = cue_dir / source_name if source_name else None

    # Поиск аудиофайла, если указанный в CUE не найден
    if not source_path or not source_path.exists():
        print("[WARN] Исходный файл не найден. Поиск альтернатив...")
        valid_exts = [".flac", ".ape", ".wav", ".wv"]
        found_audio = [f for f in cue_dir.glob("*") if f.suffix.lower() in valid_exts]
        if found_audio:
            source_path = found_audio[0]
            print(f"[INFO] Использую аудио: {source_path.name}")
        else:
            print("[ERROR] Аудиофайл (FLAC/APE) не найден в папке.")
            return

    ffmpeg_path = resolve_ffmpeg(report)
    out_dir = Path(args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    enc_args = encode_args(getattr(args, "quality", DEFAULT_QUALITY))

    total_tracks = len(tracks)
    print(f"\n[INFO] Обработка: {source_path.name} -> MP3")
    print("-" * 60)

    report.start(total_tracks, f"Нарезка: {source_path.name}")
    failed = 0

    for i, track in enumerate(tracks, start=1):
        track_title = track.get("TITLE", f"Track {i}")
        track_performer = track.get("PERFORMER", album_meta.get("PERFORMER", "Unknown Artist"))
        start_sec = time_to_seconds(track.get("TIME", "00:00:00"))
        end_sec = time_to_seconds(tracks[i]["TIME"]) if i < total_tracks else None

        print(f"{i:02d}/{total_tracks}: {track_performer} - {track_title}")
        report.update(i - 1, total_tracks, f"{track_performer} — {track_title}")

        cmd = [ffmpeg_path, "-i", str(source_path)]
        if start_sec > 0:
            cmd.extend(["-ss", f"{start_sec:.3f}"])
        if end_sec is not None:
            cmd.extend(["-to", f"{end_sec:.3f}"])
        cmd.extend([*enc_args, "-y", "-loglevel", "error", str(out_dir / f"track_{i:02d}.mp3")])

        try:
            # Вывод FFmpeg не нужен: ход работы виден на полосе прогресса.
            # run_process подавляет консольное окно на Windows — иначе
            # на каждый трек всплывало бы чёрное окно командной строки.
            run_process(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            print(f"  [FAIL] Ошибка FFmpeg на треке {i}")
            if exc.stderr:
                detail = exc.stderr.decode("utf-8", "replace").strip()
                if detail:
                    print(f"         {detail.splitlines()[-1][:200]}")
            failed += 1
            continue

    report.update(total_tracks, total_tracks, "Запись метаданных")

    # Обложка: сначала ссылка из поля, затем теги/файл рядом с альбомом.
    cover_url = getattr(args, "cover", "") or ""
    cover_data, cover_mime = download_cover(cover_url)

    if not cover_data:
        cover_data = extract_cover(source_path, cue_dir)
        cover_mime = get_mime_type(cover_data) if cover_data else "image/jpeg"
        if cover_data:
            print(f"[INFO] Обложка взята из тегов или папки "
                  f"({round(len(cover_data) / 1024, 1)} КБ)")

    if not cover_data:
        print("[INFO] Обложка не найдена — теги будут без картинки.")

    print("-" * 60)
    print("[INFO] Запись метаданных...")

    for i, track in enumerate(tracks, start=1):
        mp3_file = out_dir / f"track_{i:02d}.mp3"
        if not mp3_file.exists():
            continue

        audio = MP3(mp3_file)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.version = (2, 4, 0)

        enc = 3  # UTF-8
        audio.tags.add(TIT2(encoding=enc, text=[track.get("TITLE", "")]))
        audio.tags.add(TPE1(encoding=enc, text=[track.get("PERFORMER", "")]))
        audio.tags.add(TALB(encoding=enc, text=[album_meta.get("TITLE", "")]))
        audio.tags.add(TDRC(encoding=enc, text=[album_meta.get("DATE", "")]))
        audio.tags.add(TCON(encoding=enc, text=[album_meta.get("GENRE", "")]))
        audio.tags.add(TRCK(encoding=enc, text=[f"{i:02d}"]))

        if cover_data:
            audio.tags.add(APIC(encoding=enc, mime=cover_mime, type=3, desc="Cover", data=cover_data))

        audio.save(v2_version=4)

        # Переименование
        clean_title = re.sub(r'[<>:"/\\|?*]', "", track.get("TITLE", "Track")).strip()
        new_name = f"{i:02d} - {clean_title}.mp3"
        final_path = out_dir / new_name
        os.replace(mp3_file, final_path)

    print(f"[DONE] Альбом готов в: {out_dir}")
    report.finish(f"Готово: {total_tracks} треков" if not failed
                  else f"Готово, с ошибками: {failed} из {total_tracks}")
    return {"tracks": total_tracks, "failed": failed, "out_dir": str(out_dir)}
