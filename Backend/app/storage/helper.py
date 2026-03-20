from pathlib import Path
from app.storage.storage_service import get_storage


class StorageHelper:
    def __init__(self):
        self.storage = get_storage()

    def upload(self, path: str, file: str) -> str:
        return self.storage.upload(path=path, file=file)

    def ensure_dir(self, path: str) -> str:
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        return str(p)

    def exists(self, path: str) -> bool:
        return Path(path).exists()

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        return Path(path).read_text(encoding=encoding)

    def write_text(self, path: str, content: str, encoding: str = "utf-8") -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return str(p)
