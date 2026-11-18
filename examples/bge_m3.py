"""Use a locally supplied BGE-M3 model for conservative duplicate candidates."""

from __future__ import annotations

import argparse
import asyncio
import math
import os
from pathlib import Path
from uuid import uuid4

from sufficiency_engine import ClarificationQuestion, EmbeddingModelABC
from sufficiency_engine._clarification import deduplicate_questions


class BGEEmbedding(EmbeddingModelABC):
    """Run FlagEmbedding's BGE-M3 API on the CPU without network downloads."""

    def __init__(self, model_directory: Path) -> None:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_DATASETS_OFFLINE"] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        from FlagEmbedding import BGEM3FlagModel

        self.model = BGEM3FlagModel(
            str(model_directory), use_fp16=False, devices="cpu", trust_remote_code=False
        )
        self.last_vectors: list[list[float]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        result = await asyncio.to_thread(
            self.model.encode,
            texts,
            batch_size=2,
            max_length=64,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        self.last_vectors = [[float(value) for value in vector] for vector in result["dense_vecs"]]
        return self.last_vectors


class UnavailableEmbedding(EmbeddingModelABC):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("illustrative local model failure")


async def main(model_directory: Path) -> None:
    if not model_directory.is_dir() or not (model_directory / "config.json").is_file():
        raise ValueError("provide a complete local BGE-M3 model directory")
    requirement_id = uuid4()
    questions = [
        ClarificationQuestion(
            requirement_ids=(requirement_id,),
            text=text,
            reason="Determine the target platform.",
        )
        for text in ("Which platform should be used?", "Which platform should be used now?")
    ]
    embedding = BGEEmbedding(model_directory)
    retained, warnings = await deduplicate_questions(questions, embedding, timeout=600)
    assert len(embedding.last_vectors) == 2
    assert all(len(vector) == 1024 for vector in embedding.last_vectors)
    assert all(math.isfinite(value) for vector in embedding.last_vectors for value in vector)
    assert len(retained) == 2
    fallback, fallback_warnings = await deduplicate_questions(questions, UnavailableEmbedding())
    assert len(fallback) == 2
    assert fallback_warnings[0].code == "embedding_unavailable"
    print(f"BGE-M3: 2 x 1024 finite CPU embeddings; {len(warnings)} candidate warnings.")
    print("Lexical fallback retained both questions and reported the model failure.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True, help="Local BGE-M3 directory")
    args = parser.parse_args()
    asyncio.run(main(args.model_dir))
