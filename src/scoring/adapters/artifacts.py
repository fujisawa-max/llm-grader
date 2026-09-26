"""Compatibility access to the existing ``runs/<run>/`` artifact layout."""

from pathlib import Path

from ..core import digest, read_json, write_json


class RunArtifactAdapter:
    """Read and write run artifacts without changing their on-disk format."""

    def __init__(self, run):
        self.run = Path(run).resolve()

    def path(self, relative):
        path = (self.run / relative).resolve()
        if not path.is_relative_to(self.run):
            raise ValueError("run外のartifact参照は禁止")
        return path

    def read(self, relative):
        return read_json(self.path(relative))

    def write(self, relative, value):
        target = self.path(relative)
        write_json(target, value)
        return target

    def checksum(self, relative):
        return digest(self.path(relative))

    def checkpoint_valid(self, relative, status_relative):
        """Check the same result hash contract used by the legacy CLI."""
        result = self.path(relative)
        status = self.read(status_relative)
        return (status.get("state") == "success" and result.is_file()
                and status.get("result_sha256") == digest(result))

    def manifest(self):
        return self.read("manifest.json")
