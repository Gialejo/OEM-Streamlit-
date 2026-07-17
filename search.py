"""
search.py
Ricerca full-text "smart" sul dataframe aziende: matching su piu' campi
contemporaneamente, tolleranza a typo/accenti, ranking per rilevanza.

Motivazione: con ~3300 record una libreria di full-text search dedicata
(es. Whoosh, Elasticsearch) sarebbe sovradimensionata e pesante per un
piano gratuito Render. Il dataset intero sta comodamente in memoria, quindi
si applica prima il filtro strutturato in SQL (regione, categoria, ecc.) e
poi si calcola in Python un punteggio di rilevanza sul sottoinsieme
risultante, ordinando i risultati dal piu' pertinente.
"""

import difflib
import re
import unicodedata

# Peso per campo: un match sul nome conta molto piu' di uno nella descrizione.
FIELD_WEIGHTS = {
    "nome": 5.0,
    "descrizione_ai": 2.0,
    "descrizione_originale": 1.5,
    "categoria_mecspe_display": 1.2,
    "settore_display": 1.0,
    "provincia": 0.8,
    "citta": 0.8,
}


def normalize_text(s: str | None) -> str:
    """Minuscolo + rimozione accenti (NFKD), per confronti tolleranti agli accenti."""
    if not isinstance(s, str) or not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def tokenize(s: str | None) -> list[str]:
    return re.findall(r"\w+", normalize_text(s))


def _field_score(query_tokens: list[str], field_text: str | None) -> float:
    if not field_text:
        return 0.0
    field_norm = normalize_text(field_text)
    score = 0.0

    # Match esatto dell'intera query come sottostringa: segnale piu' forte.
    full_query = " ".join(query_tokens)
    if full_query and full_query in field_norm:
        score += 3.0

    field_tokens = set(tokenize(field_text))
    for qt in query_tokens:
        if qt in field_tokens:
            score += 1.0
        else:
            # Tolleranza ai typo: miglior match approssimativo (es. "packagig" -> "packaging").
            close = difflib.get_close_matches(qt, field_tokens, n=1, cutoff=0.8)
            if close:
                score += 0.6
    return score


def compute_relevance(record: dict, query: str) -> float:
    """Calcola un punteggio di rilevanza di 'record' rispetto a 'query',
    sommando i punteggi pesati sui vari campi testuali."""
    query_tokens = tokenize(query)
    if not query_tokens:
        return 0.0
    total = 0.0
    for field, weight in FIELD_WEIGHTS.items():
        total += weight * _field_score(query_tokens, record.get(field))
    return total
