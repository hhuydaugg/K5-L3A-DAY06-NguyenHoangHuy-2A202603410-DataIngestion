"""Local Sentence Transformers embedder (real model; no mock fallback)."""
from pathlib import Path
from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class MyEmbedder:
    """BGE models: documents encoded as-is, queries get the model card's retrieval instruction."""

    QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", batch_size: int = 32) -> None:
        from sentence_transformers import SentenceTransformer  # heavy import; errors surface to caller
        import huggingface_hub

        self.model_name = model_name
        self.batch_size = batch_size
        self.model = SentenceTransformer(model_name, device="cpu")
        self.dimensions = self.model.get_embedding_dimension()
        self.max_seq_length = self.model.max_seq_length
        ref = Path(huggingface_hub.constants.HF_HUB_CACHE) / f"models--{model_name.replace('/', '--')}" / "refs" / "main"
        self.revision = ref.read_text().strip() if ref.exists() else "unknown"

    def count_tokens(self, texts: list[str]) -> list[int]:
        return [len(ids) for ids in self.model.tokenizer(texts, add_special_tokens=True)["input_ids"]]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                 show_progress_bar=False).tolist()

    def embed_query(self, question: str) -> list[float]:
        return self.model.encode(self.QUERY_INSTRUCTION + question, normalize_embeddings=True).tolist()
