# CodeTwin Intelligence Layer

This module provides AST-aware repository indexing, code chunking, semantic vector embeddings, and retrieval-augmented generation (RAG):

- **AST Chunking**: Chunking strategy aligned with symbol boundaries (classes, functions, interfaces) rather than naive token splitting.
- **Vector Embeddings**: Compatible with OpenAI embeddings, Ollama (`nomic-embed-text`), and local HuggingFace sentence-transformers.
- **Graph RAG**: Combines vector similarity with deterministic AST call graph and dependency relationships to eliminate LLM hallucinations.
- **Evidence Verification**: Verifies all retrieved context against file paths, commit hashes, and line ranges.
