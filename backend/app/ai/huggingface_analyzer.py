import os
from typing import Iterator

from huggingface_hub import InferenceClient

from app.ai.batched import BatchedAnalyzer


class HuggingFaceAnalyzer(BatchedAnalyzer):

    def __init__(self):
        super().__init__()
        self.api_token = os.getenv("HF_API_TOKEN")
        self.model = os.getenv(
            "HF_MODEL",
            "Qwen/Qwen3-4B-Instruct-2507"
        )

        if not self.api_token:
            raise ValueError(
                "HF_API_TOKEN is not configured."
            )

        self.client = InferenceClient(
            api_key=self.api_token
        )

    def _stream_completion(
        self,
        system: str,
        user: str,
        max_tokens: int,
    ) -> Iterator[str]:
        stream = self.client.chat_completion(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
            max_tokens=max_tokens,
            stream=True,
        )

        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
