import os

from app.ai.analyzer import AIAnalyzer


def get_analyzer() -> AIAnalyzer:
    provider = os.getenv("AI_PROVIDER", "ollama").lower()

    # Imported lazily so one provider's missing package doesn't break the other.
    if provider == "ollama":
        from app.ai.ollama_analyzer import OllamaAnalyzer
        return OllamaAnalyzer()

    if provider == "huggingface":
        from app.ai.huggingface_analyzer import HuggingFaceAnalyzer
        return HuggingFaceAnalyzer()

    raise ValueError(f"Unknown AI_PROVIDER: {provider}")
