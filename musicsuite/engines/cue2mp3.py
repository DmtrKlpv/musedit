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

from mutagen import File as MutagenFile
from mutagen.mp3 import MP3
from mutagen.id3 import TIT2, TPE1, TALB, TDRC, TCON, TRCK, APIC
from mutagen.flac import FLAC, Picture
from mutagen.apev2 import APEv2

from ..progress import as_progress
from ..subproc import popen

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

# ---------------------------------------------------------------------------
# Формат треков на выходе
# ---------------------------------------------------------------------------

FORMAT_FLAC = "flac"
FORMAT_MP3 = "mp3"

# Ключ — подпись в списке, значение — внутренний код
FORMAT_LABELS = {
    "FLAC — без потерь": FORMAT_FLAC,
    "MP3 — VBR или CBR": FORMAT_MP3,
}

# FLAC по умолчанию: альбом режется без потери качества, а MP3 из него
# можно сделать позже — обратное невозможно.
DEFAULT_FORMAT_LABEL = "FLAC — без потерь"


def resolve_format(value) -> str:
    """Приводит выбор пользователя к внутреннему коду формата.

    Принимает и подпись из списка («FLAC — без потерь»), и код («flac»).
    Неизвестное значение заменяется на формат по умолчанию.
    """
    if value in FORMAT_LABELS:
        return FORMAT_LABELS[value]
    if value in FORMAT_LABELS.values():
        return value
    return FORMAT_LABELS[DEFAULT_FORMAT_LABEL]


def extension(fmt: str) -> str:
    """Расширение файлов треков для формата."""
    return ".flac" if fmt == FORMAT_FLAC else ".mp3"


def encode_args_for(fmt: str, quality: str = DEFAULT_QUALITY):
    """Аргументы FFmpeg для выбранного формата и качества.

    Для FLAC качество не указывается: сжатие без потерь, уровень влияет
    только на размер файла, а не на звук. Для MP3 — обычный выбор VBR/CBR.
    """
    if fmt == FORMAT_FLAC:
        # Уровень сжатия по умолчанию (5) — разумный баланс скорости
        # и размера; на звук он не влияет.
        return ["-c:a", "flac", "-compression_level", "5"]
    return encode_args(quality)

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
                        help="Путь к файлу обложки (JPEG/PNG/GIF/WEBP/BMP) "
                             "для встраивания в теги")
    parser.add_argument("-f", "--format", default=DEFAULT_FORMAT_LABEL,
                        choices=list(FORMAT_LABELS) + list(FORMAT_LABELS.values()),
                        help="Формат треков: FLAC (по умолчанию) или MP3")
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


# Расширения, которые принимаем как обложку
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")


def _looks_like_image(data: bytes) -> bool:
    """Проверяет сигнатуру файла, а не расширение.

    Расширение легко переименовать: «cover.jpg», внутри которого лежит
    HTML-страница, встроился бы в теги и сломал отображение у плеера.
    """
    return (
        data.startswith(b"\xff\xd8\xff")          # JPEG
        or data.startswith(b"\x89PNG\r\n\x1a\n")   # PNG
        or data.startswith(b"GIF8")                 # GIF
        or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")  # WEBP
        or data.startswith(b"BM")                   # BMP
    )


def load_cover_file(path_value: str):
    """Читает обложку из файла на диске. Возвращает (bytes, mime) или (None, None).

    Пустое значение — не ошибка: обложка просто берётся из тегов
    исходника или из cover.jpg рядом с альбомом.

    Ошибки не пробрасываем: недоступная или битая картинка не должна
    срывать конвертацию всего альбома.
    """
    path_value = (path_value or "").strip()
    if not path_value:
        return None, None

    # Заодно ловим случай, когда в поле вставили адрес сайта:
    # подсказываем, что нужен файл, а не ссылка.
    if path_value.lower().startswith(("http://", "https://")):
        print("[WARN] Указана ссылка вместо файла. Сохраните картинку "
              "на диск и выберите её кнопкой «Файл…» — обложка "
              "не встроена.")
        return None, None

    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path

    if not path.exists():
        print(f"[WARN] Файл обложки не найден: {path}")
        return None, None

    if not path.is_file():
        print(f"[WARN] Указан не файл, а папка: {path}")
        return None, None

    try:
        data = path.read_bytes()
    except OSError as exc:
        print(f"[WARN] Не удалось прочитать обложку: {exc}")
        return None, None

    if not data:
        print("[WARN] Файл обложки пустой, пропускаю.")
        return None, None

    if not _looks_like_image(data):
        print(f"[WARN] Файл {path.name} не похож на картинку "
              f"(нужен JPEG, PNG, GIF, WEBP или BMP) — обложка не встроена.")
        return None, None

    mime = get_mime_type(data)
    size_kb = round(len(data) / 1024, 1)
    print(f"[INFO] Обложка: {path.name}, {size_kb} КБ, {mime}")
    return data, mime


def get_mime_type(data: bytes) -> str:
    """MIME по сигнатуре файла.

    Раньше всё, что не JPEG и не PNG, объявлялось image/jpeg — из-за
    этого GIF и WEBP встраивались с неверным типом, и плееры могли
    отказаться показывать обложку.
    """
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"GIF8"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"BM"):
        return "image/bmp"
    return "image/jpeg"


def _source_duration(path: Path) -> float:
    """Длительность исходного аудио в секундах (0, если не определилась).

    Нужна для прогресса внутри последнего трека: его конец совпадает
    с концом файла, и без этого полоса стояла бы на месте.
    """
    try:
        audio = MutagenFile(path)
        if audio is not None and audio.info is not None:
            return float(audio.info.length)
    except Exception:
        pass
    return 0.0


def _encode_track(ffmpeg_path: str, source_path: Path, out_path: Path,
                  start_sec: float, end_sec, enc_args, track_seconds: float,
                  report, index: int, total_tracks: int) -> tuple[bool, str]:
    """Кодирует один трек и отдаёт прогресс внутри него.

    Возвращает (успех, текст ошибки).

    Почему -ss стоит ДО -i
    ----------------------
    Позиция -ss перед -i означает «перейти к этому месту во входном файле»:
    FFmpeg пользуется индексом контейнера и начинает декодировать сразу
    с нужной секунды. Если поставить -ss после -i, FFmpeg обязан
    декодировать файл с самого начала и выбрасывать всё до точки разреза.
    На 30-минутном FLAC последний трек кодировался в 6 раз дольше первого,
    а на часовом винил-рипе это выглядело как зависание на 87%.

    -t задаёт длительность куска, а не абсолютное время конца: при
    -ss перед -i метки времени начинаются с нуля, и -to отсчитал бы
    не от начала трека, а от начала файла.

    -nostdin запрещает FFmpeg читать stdin. В графическом приложении
    stdin не подключён к терминалу, и без флага процесс может ждать
    ввода, из-за чего конвертация останавливается без ошибки.
    """
    cmd = [ffmpeg_path, "-nostdin", "-hide_banner", "-loglevel", "error"]

    if start_sec and start_sec > 0:
        cmd.extend(["-ss", f"{start_sec:.3f}"])
    cmd.extend(["-i", str(source_path)])

    if end_sec is not None:
        piece = max(0.0, float(end_sec) - float(start_sec))
        cmd.extend(["-t", f"{piece:.3f}"])

    cmd.extend([*enc_args, "-progress", "pipe:1", "-nostats",
                "-y", str(out_path)])

    try:
        process = popen(cmd, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, text=True,
                        encoding="utf-8", errors="replace", bufsize=1)
    except Exception as exc:  # noqa: BLE001
        return False, f"не удалось запустить FFmpeg: {exc}"

    noise = []
    try:
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            if line.startswith("out_time_us="):
                # FFmpeg отдаёт микросекунды; делим на длительность трека.
                raw = line.split("=", 1)[1]
                try:
                    done_sec = int(raw) / 1_000_000
                except ValueError:
                    continue
                if track_seconds > 0:
                    fraction = min(1.0, max(0.0, done_sec / track_seconds))
                    # Сдвигаем на долю трека: полоса движется и внутри него,
                    # а не только между треками.
                    report.update(index - 1 + fraction, total_tracks,
                                  f"{index:02d}/{total_tracks}")
            elif not line.startswith(("frame=", "fps=", "bitrate=", "total_size=",
                                      "out_time=", "dup_frames=", "drop_frames=",
                                      "speed=", "progress=")):
                noise.append(line)
    finally:
        try:
            process.stdout.close()
        except Exception:
            pass
        code = process.wait()

    if code != 0:
        detail = noise[-1][:200] if noise else f"код возврата {code}"
        return False, detail
    return True, ""


def _write_mp3_tags(path: Path, track: dict, album_meta: dict,
                    number: int, cover_data, cover_mime: str) -> None:
    """Пишет ID3v2.4 (UTF-8) в MP3 и встраивает обложку в APIC-кадр."""
    audio = MP3(path)
    if audio.tags is None:
        audio.add_tags()
    audio.tags.version = (2, 4, 0)

    enc = 3  # UTF-8
    audio.tags.add(TIT2(encoding=enc, text=[track.get("TITLE", "")]))
    audio.tags.add(TPE1(encoding=enc, text=[track.get("PERFORMER", "")]))
    audio.tags.add(TALB(encoding=enc, text=[album_meta.get("TITLE", "")]))
    audio.tags.add(TDRC(encoding=enc, text=[album_meta.get("DATE", "")]))
    audio.tags.add(TCON(encoding=enc, text=[album_meta.get("GENRE", "")]))
    audio.tags.add(TRCK(encoding=enc, text=[f"{number:02d}"]))

    if cover_data:
        audio.tags.add(APIC(encoding=enc, mime=cover_mime, type=3,
                            desc="Cover", data=cover_data))

    audio.save(v2_version=4)


def _write_flac_tags(path: Path, track: dict, album_meta: dict,
                     number: int, cover_data, cover_mime: str) -> None:
    """Пишет Vorbis-комментарии и картинку в FLAC.

    У FLAC своя схема тегов (Vorbis comments), а обложка хранится не в
    APIC-кадре, а отдельным блоком PICTURE — поэтому запись отличается
    от MP3 и вынесена в отдельную функцию.
    """
    audio = FLAC(path)

    audio["title"] = track.get("TITLE", "")
    audio["artist"] = track.get("PERFORMER", "")
    audio["album"] = album_meta.get("TITLE", "")
    audio["date"] = album_meta.get("DATE", "")
    audio["genre"] = album_meta.get("GENRE", "")
    audio["tracknumber"] = f"{number:02d}"

    if cover_data:
        picture = Picture()
        picture.type = 3          # front cover
        picture.mime = cover_mime
        picture.desc = "Cover"
        picture.data = cover_data
        # add_picture сам удаляет прежние картинки того же типа
        audio.clear_pictures()
        audio.add_picture(picture)

    audio.save()


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

    # Формат выбирается в интерфейсе; по умолчанию FLAC.
    out_format = resolve_format(getattr(args, "format", DEFAULT_FORMAT_LABEL))
    out_ext = extension(out_format)
    enc_args = encode_args_for(
        out_format, getattr(args, "quality", DEFAULT_QUALITY)
    )

    format_name = "FLAC" if out_format == FORMAT_FLAC else "MP3"
    total_tracks = len(tracks)
    print(f"\n[INFO] Обработка: {source_path.name} -> {format_name}")
    print("-" * 60)

    report.start(total_tracks, f"Нарезка: {source_path.name}")
    failed = 0

    # Полная длительность исходника: нужна, чтобы последний трек тоже
    # показывал прогресс (у него нет следующей метки и, значит, конца).
    source_seconds = _source_duration(source_path)

    for i, track in enumerate(tracks, start=1):
        track_title = track.get("TITLE", f"Track {i}")
        track_performer = track.get("PERFORMER", album_meta.get("PERFORMER", "Unknown Artist"))
        start_sec = time_to_seconds(track.get("TIME", "00:00:00"))
        end_sec = time_to_seconds(tracks[i]["TIME"]) if i < total_tracks else None

        print(f"{i:02d}/{total_tracks}: {track_performer} - {track_title}")
        report.update(i - 1, total_tracks, f"{track_performer} — {track_title}")

        # Длительность куска — для расчёта прогресса внутри трека.
        if end_sec is not None:
            track_seconds = max(0.0, end_sec - start_sec)
        elif source_seconds > 0:
            track_seconds = max(0.0, source_seconds - start_sec)
        else:
            track_seconds = 0.0

        ok, error = _encode_track(
            ffmpeg_path, source_path, out_dir / f"track_{i:02d}{out_ext}",
            start_sec, end_sec, enc_args, track_seconds,
            report, i, total_tracks,
        )
        if not ok:
            print(f"  [FAIL] Ошибка FFmpeg на треке {i}")
            if error:
                print(f"         {error}")
            failed += 1
            continue

    report.update(total_tracks, total_tracks, "Запись метаданных")

    # Обложка: сначала ссылка из поля, затем теги/файл рядом с альбомом.
    cover_file = getattr(args, "cover", "") or ""
    cover_data, cover_mime = load_cover_file(cover_file)

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
        track_file = out_dir / f"track_{i:02d}{out_ext}"
        if not track_file.exists():
            continue

        if out_format == FORMAT_FLAC:
            _write_flac_tags(track_file, track, album_meta, i, cover_data, cover_mime)
        else:
            _write_mp3_tags(track_file, track, album_meta, i, cover_data, cover_mime)

        # Переименование
        clean_title = re.sub(r'[<>:"/\\|?*]', "", track.get("TITLE", "Track")).strip()
        new_name = f"{i:02d} - {clean_title}{out_ext}"
        final_path = out_dir / new_name
        os.replace(track_file, final_path)

    print(f"[DONE] Альбом готов в: {out_dir}")
    report.finish(f"Готово: {total_tracks} треков" if not failed
                  else f"Готово, с ошибками: {failed} из {total_tracks}")
    return {"tracks": total_tracks, "failed": failed, "out_dir": str(out_dir)}
