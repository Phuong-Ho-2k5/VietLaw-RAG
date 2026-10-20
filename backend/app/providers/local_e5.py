from functools import lru_cache

from app.core.config import MODEL_REVISION, Settings
from app.core.errors import DomainError
from app.providers.embedding import checked_vector, default_profile

MODEL_FILES = ["*.json", "*.safetensors", "*.txt", "*.model"]
EXCLUDED_FILES = ["onnx/*", "openvino/*"]


class LocalE5:
    profile = default_profile()

    def __init__(self):
        from huggingface_hub import snapshot_download
        from sentence_transformers import SentenceTransformer

        try:
            path = snapshot_download(
                self.profile.model,
                revision=MODEL_REVISION,
                cache_dir=str(Settings().model_cache),
                local_files_only=True,
                allow_patterns=MODEL_FILES,
                ignore_patterns=EXCLUDED_FILES,
            )
            self.model = SentenceTransformer(
                path, device="cpu", local_files_only=True, trust_remote_code=False
            )
        except OSError:
            raise DomainError(
                "MODEL_NOT_PREPARED", 503, "Run prepare-model before starting embedding work"
            ) from None
        if self.model.get_embedding_dimension() != 384 or self.model.max_seq_length < 512:
            raise DomainError("MODEL_CONFIGURATION_MISMATCH", 503)

    def encode(self, texts: list[str], prefix: str) -> list[list[float]]:
        inputs = [prefix + text for text in texts]
        for value in inputs:
            ids = self.model.tokenizer(value, truncation=False, add_special_tokens=True)[
                "input_ids"
            ]
            if len(ids) > self.profile.max_tokens:
                raise DomainError("EMBEDDING_INPUT_TOO_LONG", 422)
        vectors = self.model.encode(
            inputs, batch_size=8, normalize_embeddings=True, show_progress_bar=False
        )
        return [checked_vector(v) for v in vectors]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self.encode(texts, "passage: ")

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self.encode(texts, "query: ")


@lru_cache(maxsize=1)
def get_provider() -> LocalE5:
    return LocalE5()


def prepare_model():
    from huggingface_hub import snapshot_download

    return snapshot_download(
        default_profile().model,
        revision=MODEL_REVISION,
        cache_dir=str(Settings().model_cache),
        allow_patterns=MODEL_FILES,
        ignore_patterns=EXCLUDED_FILES,
    )
