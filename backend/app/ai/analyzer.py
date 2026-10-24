from abc import ABC, abstractmethod
from pathlib import PureWindowsPath
from typing import Any, Iterator

from app.models.ai_schemas import CleanupPlan, FileAnalysis


class AIAnalyzer(ABC):
    """
    Interface for AI-powered file analysis.

    The rest of the application should depend on this interface,
    not on a specific AI provider or model.
    """

    @abstractmethod
    def analyze(self, files: list[dict[str, Any]]) -> CleanupPlan:
        """
        Analyze a collection of files and return a cleanup plan.
        """
        raise NotImplementedError

    def analyze_stream(
        self,
        files: list[dict[str, Any]],
    ) -> Iterator[FileAnalysis]:
        """
        Yield analyses as they become ready. Providers that work
        file by file should override this so results show up live.
        """
        yield from self.analyze(files).analyses


def is_safe_destination(destination: str) -> bool:
    """A destination must stay inside the scanned folder."""
    path = PureWindowsPath(destination)

    return bool(destination.strip()) and not (
        path.is_absolute()
        or path.drive
        or path.root
        or ".." in path.parts
    )
