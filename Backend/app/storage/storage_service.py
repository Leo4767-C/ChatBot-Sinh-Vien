from pathlib import Path
import shutil
from typing import BinaryIO

from fastapi import UploadFile


class LocalStorageService:
    def __init__(self, base_dir: str = "data/storage"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir = Path(__file__).resolve().parents[2] / "data"

    def upload(self, path: str, file: str) -> str:
        src = Path(file)
        if not src.exists():
            raise FileNotFoundError(f"File không tồn tại: {file}")

        dest_dir = Path(path)
        if not dest_dir.is_absolute():
            dest_dir = self.base_dir / dest_dir

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        shutil.copy2(src, dest)
        return str(dest)

    def _resolve_source(self, path: str) -> Path:
        """
        Ưu tiên file local thật trước.
        Nếu không có thì mới fallback sang storage base_dir.
        """
        p = Path(path)

        if p.is_absolute() and p.exists():
            return p

        if p.exists():
            return p.resolve()

        storage_p = self.base_dir / p
        if storage_p.exists():
            return storage_p.resolve()

        raise FileNotFoundError(f"File không tồn tại trong storage: {storage_p}")

    def download(self, path: str, local_path: str | None = None):
        src = self._resolve_source(path)

        if local_path:
            dest = Path(local_path)
            if dest.exists() and dest.is_dir():
                dest = dest / src.name
            elif str(local_path).endswith("/") or (not dest.suffix and not dest.exists()):
                dest.mkdir(parents=True, exist_ok=True)
                dest = dest / src.name

            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            return open(dest, "rb")

        return open(src, "rb")

    def exists(self, name: str) -> bool:
        try:
            self._resolve_source(name)
            return True
        except FileNotFoundError:
            return False

    def path(self, name: str) -> str:
        return str(self._resolve_source(name))

    def upload_v2(self, path: Path | str, file: UploadFile) -> Path | None:
        full_path = self.upload_dir / path
        directory = full_path.parent
        directory.mkdir(parents=True, exist_ok=True)

        try:
            with open(full_path, "wb") as f:
                shutil.copyfileobj(file.file, f)
            return full_path
        except Exception as e:
            return None
        finally:
            file.file.close()

    def download_v2(self, path: Path | str):
        full_path = self.upload_dir / path
        if not full_path.is_file():
            return None
        try:
            file_stream: BinaryIO = open(full_path, 'rb')
            return file_stream
        except Exception:
            return None


_storage = LocalStorageService()


def get_storage() -> LocalStorageService:
    return _storage