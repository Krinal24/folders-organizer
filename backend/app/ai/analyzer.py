from abc import ABC, abstractmethod
from typing import Any


class AIAnalyzer(ABC):
    """
    Interface for AI-powered file analysis.

    The rest of the application should depend on this interface,
    not on a specific AI provider or model.
    """

    @abstractmethod
    def analyze(self, files: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Analyze a collection of files and return a cleanup plan.
        """
        raise NotImplementedError