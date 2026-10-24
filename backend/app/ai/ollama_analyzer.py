import os
from typing import Iterator

from ollama import chat

from app.ai.batched import BatchedAnalyzer


class OllamaAnalyzer(BatchedAnalyzer):
    def __init__(self):
        super().__init__()
        self.model = os.getenv("OLLAMA_MODEL", "gemma3:4b")

    def _stream_completion(
        self,
        system: str,
        user: str,
        max_tokens: int,
    ) -> Iterator[str]:
        stream = chat(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            stream=True,
            # Keep the model loaded between batches and runs.
            keep_alive="30m",
            options={
                "temperature": 0,
                "num_ctx": 8192,
                "num_predict": max_tokens,
            },
        )

        for chunk in stream:
            yield chunk.message.content
