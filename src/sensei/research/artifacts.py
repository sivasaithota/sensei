"""Atomic, immutable persistence for evidence dossiers."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from sensei.research.models import EvidenceDossier


class ImmutableEvidenceStore:
    def __init__(self, artifact_dir: Path) -> None:
        self._artifact_dir = Path(artifact_dir)

    def record(self, dossier: EvidenceDossier) -> None:
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        digest = dossier.experiment_id.removeprefix("sha256:")
        destination = self._artifact_dir / f"{digest}.json"
        payload = (dossier.model_dump_json(indent=2) + "\n").encode()

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self._artifact_dir, delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.chmod(0o444)
            try:
                os.link(temporary_path, destination)
            except FileExistsError:
                if destination.read_bytes() != payload:
                    raise RuntimeError(
                        f"experiment artifact collision or corruption: {destination}"
                    )
            else:
                directory_fd = os.open(self._artifact_dir, os.O_RDONLY)
                try:
                    try:
                        os.fsync(directory_fd)
                    except Exception:
                        destination.unlink(missing_ok=True)
                        raise
                finally:
                    os.close(directory_fd)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
