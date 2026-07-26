"""Corpus reglementaire editorial — ingestion, index, recherche."""
from backend.corpus.ingestion import ingerer_document, seed_corpus_demo
from backend.corpus.recherche import recherche_hybride

__all__ = ["ingerer_document", "recherche_hybride", "seed_corpus_demo"]
