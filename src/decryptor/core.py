"""Decrypt Ridibooks books into title-named folders."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import zipfile
from pathlib import Path
from typing import Callable, Optional

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

HEADER_SIZE = 256
SIGNATURE = 1684108385  # b"data"
VERSION_OFFSET = 4
STORE_NAME_OFFSET = 8
STORE_NAME_LEN_OFFSET = 72
CHECKSUM_OFFSET = 108
CHECKSUM_LEN = 40
MAX_VERSION = 4

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
Log = Callable[[str], None]
Progress = Callable[[int, int, str, int, int], None]


def content_key(book_id: str, user_idx: str) -> bytes:
    digest = hashlib.sha1(f"{book_id}-{user_idx}".encode("utf-8")).hexdigest()
    return digest[2:18].encode("ascii")


def decrypt_book_meta(data: bytes, user_idx: str) -> dict:
    if len(data) < HEADER_SIZE or (len(data) - HEADER_SIZE) % 16 != 0:
        raise ValueError(f"invalid BOOK_META size: {len(data)}")

    signature = int.from_bytes(data[0:4], "big")
    if signature != SIGNATURE:
        raise ValueError("invalid BOOK_META signature")

    version = int.from_bytes(data[VERSION_OFFSET:VERSION_OFFSET + 4], "big")
    if version == 0 or version > MAX_VERSION:
        raise ValueError(f"unsupported BOOK_META version: {version}")

    name_len = int.from_bytes(data[STORE_NAME_LEN_OFFSET:STORE_NAME_LEN_OFFSET + 2], "big")
    if name_len < 1 or STORE_NAME_OFFSET + name_len > STORE_NAME_LEN_OFFSET:
        raise ValueError(f"invalid store name length: {name_len}")

    payload = data[HEADER_SIZE:]
    checksum = data[CHECKSUM_OFFSET:CHECKSUM_OFFSET + CHECKSUM_LEN].decode("ascii")
    if checksum != hashlib.sha1(payload).hexdigest():
        raise ValueError("checksum mismatch")

    book_id = data[STORE_NAME_OFFSET:STORE_NAME_OFFSET + name_len].decode("utf-8")
    cipher = Cipher(algorithms.AES(content_key(book_id, user_idx)), modes.ECB())
    decryptor = cipher.decryptor()
    plain = decryptor.update(payload) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plain = unpadder.update(plain) + unpadder.finalize()
    return json.loads(plain.decode("utf-8"))


def book_title(meta: dict) -> str:
    data = meta.get("data")
    title = data.get("title") if isinstance(data, dict) else None
    if isinstance(title, dict):
        main = title.get("main")
        if isinstance(main, str) and main.strip():
            return main.strip()
    if isinstance(title, str) and title.strip():
        return title.strip()
    raise ValueError("BOOK_META에 제목이 없습니다")


def image_key(device_id: str) -> bytes:
    device_id = device_id.strip()
    if len(device_id) != 36:
        raise ValueError(f"Device ID는 36자여야 합니다 (현재 {len(device_id)}자)")
    key = device_id[2:18].encode("utf-8")
    if len(key) != 16:
        raise ValueError("이미지 키가 16바이트가 아닙니다")
    return key


def decrypt_image(data: bytes, key: bytes) -> bytes:
    if len(data) < 32:
        raise ValueError("데이터가 너무 작습니다")
    iv, ciphertext = data[:16], data[16:]
    if len(ciphertext) % 16 != 0:
        ciphertext = ciphertext[: len(ciphertext) - (len(ciphertext) % 16)]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


def looks_like_image(data: bytes) -> bool:
    if data.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"BM")):
        return True
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def library_dir(user_idx: str) -> Path:
    user_idx = user_idx.strip().lstrip("_")
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Ridibooks/library" / f"_{user_idx}"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            raise ValueError("APPDATA 환경변수를 찾을 수 없습니다")
        return Path(appdata) / "Ridibooks/library" / f"_{user_idx}"
    raise NotImplementedError("이 OS는 기본 라이브러리 경로를 지원하지 않습니다")


def book_meta_dir(user_idx: str) -> Path:
    user_idx = user_idx.strip().lstrip("_")
    if sys.platform == "darwin":
        base = Path.home() / "Library/Application Support/Ridibooks/datastores/user"
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            raise ValueError("APPDATA 환경변수를 찾을 수 없습니다")
        base = Path(appdata) / "Ridibooks/datastores/user"
    else:
        raise NotImplementedError("이 OS는 기본 BOOK_META 경로를 지원하지 않습니다")
    return base / f"_{user_idx}" / "BOOK_META"


def safe_folder_name(title: str) -> str:
    if sys.platform == "win32":
        name = INVALID_NAME.sub(" ", title)
    else:
        name = title.replace("/", " ").replace(":", " ")
        name = re.sub(r"[\x00-\x1f]", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:120] or "untitled"


def series_title(title: str) -> str:
    """Remove a trailing Korean volume marker to group books by series."""
    series = re.sub(r"\s*\d+\s*권(?:\s*[\[(（【].*?[\])）】])?\s*$", "", title).strip()
    return series or title


def book_folders(library: Path) -> list:
    if not library.is_dir():
        raise FileNotFoundError(f"라이브러리가 없습니다: {library}")
    folders = []
    for entry in sorted(library.iterdir()):
        if entry.is_dir() and not entry.name.startswith(".") and any(entry.glob("*.zip")):
            folders.append(entry)
    return folders


def book_zip(folder: Path) -> Path:
    exact = folder / f"{folder.name}.zip"
    if exact.is_file():
        return exact
    zips = sorted(path for path in folder.glob("*.zip") if path.is_file())
    if not zips:
        raise FileNotFoundError(f"ZIP 파일이 없습니다: {folder}")
    return zips[0]


def title_for_book(book_id: str, meta_dir: Path, user_idx: str) -> str:
    meta_path = meta_dir / book_id
    if not meta_path.is_file():
        raise FileNotFoundError(meta_path)
    return book_title(decrypt_book_meta(meta_path.read_bytes(), user_idx))


def list_books(user_idx: str, library: Optional[Path] = None, meta: Optional[Path] = None) -> list:
    user_idx = user_idx.strip().lstrip("_")
    library = (library or library_dir(user_idx)).expanduser()
    meta = (meta or book_meta_dir(user_idx)).expanduser()
    rows = []
    for folder in book_folders(library):
        try:
            title = title_for_book(folder.name, meta, user_idx)
        except Exception:
            title = folder.name
        rows.append((folder.name, title))
    return rows


def decrypt_book(
    folder: Path,
    key: bytes,
    dest: Path,
    log: Optional[Log] = None,
    on_page: Optional[Callable[[int, int], None]] = None,
    stop: Optional[threading.Event] = None,
    workers: Optional[int] = None,
) -> tuple:
    archive = book_zip(folder)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        images = [
            info for info in zipped.infolist()
            if not info.is_dir() and Path(info.filename).suffix.lower() in IMAGE_SUFFIXES
        ]
    images.sort(key=lambda info: Path(info.filename).name)
    total = len(images)
    worker_count = min(workers or 4, max(1, os.cpu_count() or 1), max(total, 1))
    reader_local = threading.local()
    readers = []
    readers_lock = threading.Lock()
    name_locks = {}
    for info in images:
        name = Path(info.filename).name
        name_locks.setdefault(name, threading.Lock())

    def init_reader() -> None:
        reader = zipfile.ZipFile(archive)
        reader_local.zip = reader
        with readers_lock:
            readers.append(reader)

    def decrypt_one(info: zipfile.ZipInfo) -> tuple[str, Optional[Exception]]:
        if stop is not None and stop.is_set():
            return Path(info.filename).name, None
        name = Path(info.filename).name
        try:
            plain = decrypt_image(reader_local.zip.read(info), key)
            if not looks_like_image(plain):
                raise ValueError("이미지 시그니처가 아닙니다")
            with name_locks[name]:
                (dest / name).write_bytes(plain)
            return name, None
        except Exception as exc:
            return name, exc

    success = fail = completed = 0
    try:
        with ThreadPoolExecutor(max_workers=worker_count, initializer=init_reader) as executor:
            futures = [executor.submit(decrypt_one, info) for info in images]
            for future in as_completed(futures):
                if stop is not None and stop.is_set():
                    break
                name, error = future.result()
                completed += 1
                if error is None:
                    success += 1
                else:
                    fail += 1
                    if log:
                        log(f"실패 {name}: {error}")
                if on_page:
                    on_page(completed, total)
    finally:
        for reader in readers:
            reader.close()
    return success, fail


def decrypt_library(
    device_id: str,
    user_idx: str,
    output: Path,
    library: Optional[Path] = None,
    meta: Optional[Path] = None,
    book_id: Optional[str] = None,
    log: Optional[Log] = None,
    on_progress: Optional[Progress] = None,
    on_status: Optional[Callable[[str], None]] = None,
    create_formats: bool = False,
    stop: Optional[threading.Event] = None,
) -> tuple:
    user_idx = user_idx.strip().lstrip("_")
    if not user_idx:
        raise ValueError("User Index를 입력해주세요")
    key = image_key(device_id)
    library = (library or library_dir(user_idx)).expanduser()
    meta = (meta or book_meta_dir(user_idx)).expanduser()
    output = output.expanduser()
    output.mkdir(parents=True, exist_ok=True)

    folders = book_folders(library)
    if book_id:
        folders = [folder for folder in folders if folder.name == book_id]
    if not folders:
        raise FileNotFoundError("복호화할 책이 없습니다")

    if log:
        log(f"저장 폴더  {output}")

    total = len(folders)
    used = set()
    tasks = []
    for index, folder in enumerate(folders, 1):
        current_id = folder.name
        try:
            title = title_for_book(current_id, meta, user_idx)
        except Exception as exc:
            title = current_id
            if log:
                log(f"{current_id} 제목을 읽지 못했습니다. {exc}")
        name = safe_folder_name(title)
        if name.casefold() in used:
            name = safe_folder_name(f"{title} ({current_id})")
        used.add(name.casefold())
        dest = output / name

        tasks.append((index, folder, title, dest))

    book_workers = min(8, max(1, (os.cpu_count() or 1) // 2), len(tasks))
    page_workers = max(1, min(4, (os.cpu_count() or 1) // book_workers))

    def process_book(task: tuple) -> str:
        index, folder, title, dest = task
        if stop is not None and stop.is_set():
            return "stopped"
        if log:
            log(f"{index}/{total}  {title}")

        def on_page(page: int, pages: int) -> None:
            if not on_progress:
                return
            on_progress(index, total, title, page, pages)

        try:
            success, page_failures = decrypt_book(folder, key, dest, log, on_page, stop, page_workers)
        except Exception as exc:
            if log:
                log(f"실패  {title}: {exc}")
            return "failed"

        if stop is not None and stop.is_set():
            if log:
                log(f"중지 요청으로 {title}의 EPUB/PDF 생성을 건너뜁니다")
            return "stopped"

        format_failed = False
        if log:
            log(f"      {dest.name}  ·  {success}장")
            if page_failures:
                log(f"      실패 {page_failures}장")
        if create_formats:
            from .ebook import create_epub, create_pdf

            series_folder = safe_folder_name(series_title(title))
            jobs = {
                "EPUB": (create_epub, output / "epub" / series_folder / f"{dest.name}.epub"),
                "PDF": (create_pdf, output / "pdf" / series_folder / f"{dest.name}.pdf"),
            }
            if on_status:
                on_status(f"{index}/{total}  {title}  ·  EPUB/PDF 동시 생성 중")
            if log:
                log(f"      EPUB/PDF 동시 생성 중")
            with ThreadPoolExecutor(max_workers=2) as format_executor:
                futures = {
                    format_executor.submit(create_file, dest, destination): (format_name, destination)
                    for format_name, (create_file, destination) in jobs.items()
                }
                for future in as_completed(futures):
                    format_name, destination = futures[future]
                    try:
                        pages = future.result()
                        if log:
                            log(f"      생성됨  {destination.name}  ·  {pages}장")
                    except Exception as exc:
                        format_failed = True
                        if log:
                            log(f"      {format_name} 변환 실패: {exc}")
        if create_formats and not format_failed:
            try:
                shutil.rmtree(dest)
                if log:
                    log(f"      이미지 폴더 삭제됨  {dest.name}")
            except Exception as exc:
                format_failed = True
                if log:
                    log(f"      이미지 폴더 삭제 실패: {exc}")
        return "failed" if format_failed else "done"

    done = failed = 0
    with ThreadPoolExecutor(max_workers=book_workers) as executor:
        futures = [executor.submit(process_book, task) for task in tasks]
        for future in as_completed(futures):
            result = future.result()
            if result == "done":
                done += 1
            elif result == "failed":
                failed += 1
    if stop is not None and stop.is_set() and log:
        log("중지했습니다")
    return done, failed


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Decrypt a Ridibooks library into title-named folders")
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--user-idx", required=True)
    parser.add_argument("-o", "--output", required=True, type=Path)
    parser.add_argument("--book", help="Decrypt only this book id")
    args = parser.parse_args(argv)
    try:
        done, failed = decrypt_library(
            args.device_id,
            args.user_idx,
            args.output,
            book_id=args.book,
            log=print,
        )
    except Exception as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"완료  성공 {done}권  실패 {failed}권")
    return 1 if failed else 0
