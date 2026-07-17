"""
clean_database.py
Script di pulizia e normalizzazione riutilizzabile per il database aziende.

Non modifica MAI il file sorgente: legge il JSON grezzo (es. data/database_aziende.json)
e scrive un nuovo file JSON "pulito" (default: data/database_aziende_clean.json).
Puo' essere rilanciato ogni volta che il database sorgente viene aggiornato
(es. nuovo export da MECSPE), senza perdere lavoro.

Uso:
    python clean_database.py
    python clean_database.py --input data/database_aziende.json --output data/database_aziende_clean.json

Cosa fa, in sintesi:
1. Normalizza categoria_mecspe: unisce le ~40 varianti sporche (typo, spazi
   doppi, trattini diversi, categorie concatenate senza separatore, suffissi
   "villaggio/padiglione fiera") in 13 categorie canoniche pulite.
2. Deduce un settore (settore_dedotto) via keyword-matching sulla descrizione
   quando il campo settore originale e' assente, senza mai sovrascrivere il
   dato originale e segnalando sempre la fonte (settore_fonte).
3. Calcola un livello di completezza del record (0-3) per distinguere in UI
   le aziende con dati ricchi da quelle "solo nome".
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

DEFAULT_INPUT = Path(__file__).parent / "data" / "database_aziende.json"
DEFAULT_OUTPUT = Path(__file__).parent / "data" / "database_aziende_clean.json"

# --------------------------------------------------------------------------
# Tassonomia canonica categoria_mecspe (13 categorie pulite)
# --------------------------------------------------------------------------
# Chiave: nome "grezzo" canonico (dopo normalizzazione spazi/trattini).
# Valore: etichetta pulita mostrata in UI.
RAW_TO_CLEAN_CATEGORIA = {
    "EUROSTAMPI - PLASTICA, GOMMA E COMPOSITI": "Plastica, Gomma e Compositi",
    "MATERIALI NON FERROSI E LEGHE": "Materiali Non Ferrosi e Leghe",
    "MACCHINE LAVORAZIONE LAMIERA": "Macchine Lavorazione Lamiera",
    "CONTROLLO E QUALITA'": "Controllo e Qualità",
    "AUTOMAZIONE E ROBOTICA": "Automazione e Robotica",
    "TRATTAMENTI E FINITURE": "Trattamenti e Finiture",
    "ADDITIVE MANUFACTURING": "Additive Manufacturing",
    "SUBFORNITURA MECCANICA": "Subfornitura Meccanica",
    "MACCHINE UTENSILI": "Macchine Utensili",
    "FABBRICA DIGITALE": "Fabbrica Digitale",
    "ELETTRONICA ITALIA": "Elettronica",
    "POWER DRIVE": "Trasmissione di Potenza (Power Drive)",
    "LOGISTICA": "Logistica",
}
# Matching dal nome grezzo piu' lungo al piu' corto, cosi' un nome corto
# (es. "LOGISTICA") non "ruba" per errore un pezzo di uno piu' lungo che lo contiene.
_RAW_NAMES_BY_LENGTH = sorted(RAW_TO_CLEAN_CATEGORIA, key=len, reverse=True)


def _normalize_whitespace_dashes(s: str) -> str:
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _strip_villaggio_suffix(s: str) -> str:
    """Rimuove suffissi tipo ', SUBFORNITURA - VILLAGGIO CONFARTIGIANATO' o
    ', ADDITIVE MANUFACTURING - QUARTIERE PROTOTIPAZIONE RAPIDA': sono nomi
    di padiglioni/villaggi della fiera MECSPE, non categorie aziendali, e
    vengono scartati (decisione confermata dall'utente)."""
    if "," in s:
        before, after = s.split(",", 1)
        if "VILLAGGIO" in after.upper() or "QUARTIERE" in after.upper():
            return before.strip()
    return s


def _extract_clean_categories(raw_value: str) -> list[str]:
    """Da una singola stringa dell'array categoria_mecspe (a volte con 2
    categorie concatenate senza separatore per un bug di scraping, e a volte
    con maiuscole/minuscole miste come "EUROSTAMPI - Plastica, Gomma e
    Compositi") estrae la lista di etichette pulite corrispondenti."""
    remaining = _strip_villaggio_suffix(_normalize_whitespace_dashes(raw_value))
    found = []
    for raw_name in _RAW_NAMES_BY_LENGTH:
        pattern = re.compile(re.escape(raw_name), re.IGNORECASE)
        if pattern.search(remaining):
            found.append(RAW_TO_CLEAN_CATEGORIA[raw_name])
            remaining = _normalize_whitespace_dashes(pattern.sub(" ", remaining))
    if remaining:
        print(f"  [WARN] valore categoria_mecspe non riconosciuto, ignorato: {raw_value!r} (residuo: {remaining!r})")
    return found


def normalize_categoria_mecspe(cats: list | None) -> list[str]:
    """Normalizza l'intero array categoria_mecspe di un record, deduplicando
    mantenendo l'ordine di prima apparizione."""
    if not cats:
        return []
    clean = []
    for raw in cats:
        clean.extend(_extract_clean_categories(raw))
    seen = set()
    result = []
    for c in clean:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


# --------------------------------------------------------------------------
# Deduzione settore da keyword (solo quando il settore originale e' assente)
# --------------------------------------------------------------------------
# Le chiavi ricalcano i 16 valori "atomici" gia' presenti nel campo settore
# originale (che, quando valorizzato, e' gia' una lista pulita comma-separated).
SETTORE_KEYWORDS = {
    "Agricoltura e macchine agricole": ["agricol", "trattric", "mietitrebbi", "macchine agricole"],
    "Plastica e gomma": ["plastic", "gomma", "elastomer", "stampaggio a iniezione", "poliuretan"],
    "Attrezzature e componenti per trasmissioni idrauliche": ["idraulic", "oleodinamic", "pompe idraulich", "cilindri idraulici"],
    "Calzature, pelletteria e concerie": ["calzatur", "pelletter", "concer", "cuoio"],
    "Marmo e pietra": ["marmo", "pietra natural", "lapide", "granito"],
    "Imballaggio": ["imballagg", "packaging", "confezionamento", "incartonatric"],
    "Macchine per fonderia e metallurgia": ["fonderia", "fusione dei metalli", "metallurgi", "colata"],
    "Macchinari per ceramica": ["ceramic", "piastrell", "sanitari in ceramica"],
    "Vetro": ["vetro", "vetrer", "cristallo"],
    "Lavorazione dei metalli": ["tornitura", "fresatura", "carpenteria metallic", "lavorazione dei metalli", "lavorazioni meccanich"],
    "Stampa, grafica ed elaborazione": ["stampa grafic", "tipografi", "prestampa", "settore grafico"],
    "Tecnologia alimentare": ["alimentare", "agroalimentare", "food industry", "settore alimentare"],
    "Macchine da costruzione e movimento terra": ["movimento terra", "escavator", "macchine da cantiere", "edilizia e costruzioni"],
    "Macchinari tessili": ["tessile", "tessut", "filatura", "settore tessile"],
    "Legno": ["falegnameria", "lavorazione del legno", "mobilifici", "arredamento in legno"],
    "Trasmissione di potenza e sistemi di movimento": ["trasmissione di potenza", "riduttori", "motion control", "cuscinetti volventi"],
}

# Fallback: se la descrizione non da' nessun match, alcune categoria_mecspe
# gia' normalizzate sono un indicatore ragionevolmente affidabile di settore.
CATEGORIA_TO_SETTORE_FALLBACK = {
    "Macchine Lavorazione Lamiera": "Lavorazione dei metalli",
    "Materiali Non Ferrosi e Leghe": "Lavorazione dei metalli",
}


def deduce_settore(descrizione: str | None, categorie_clean: list[str]) -> list[str]:
    hits = []
    if descrizione:
        desc_lower = descrizione.lower()
        for settore, keywords in SETTORE_KEYWORDS.items():
            if any(kw in desc_lower for kw in keywords):
                hits.append(settore)
    if not hits:
        for cat in categorie_clean:
            fallback = CATEGORIA_TO_SETTORE_FALLBACK.get(cat)
            if fallback and fallback not in hits:
                hits.append(fallback)
    return hits


# --------------------------------------------------------------------------
# Badge di completezza record (per distinguere aziende "ricche" da "solo nome")
# --------------------------------------------------------------------------
COMPLETEZZA_LABELS = {
    0: ("ricca", "🟩"),
    1: ("parziale", "🟨"),
    2: ("scarsa", "🟧"),
    3: ("solo_nome", "⬛"),
}


def compute_completezza(settore_effettivo, categorie_clean, regione, descrizione) -> tuple[int, str, str]:
    campi = [settore_effettivo, categorie_clean, regione, descrizione]
    n_null = sum(1 for c in campi if not c)
    livello = min(n_null, 3)
    label, emoji = COMPLETEZZA_LABELS[livello]
    return livello, label, emoji


def clean_record(rec: dict) -> dict:
    categorie_clean = normalize_categoria_mecspe(rec.get("categoria_mecspe"))
    settore_originale = rec.get("settore")

    settore_dedotto = None
    settore_fonte = "originale" if settore_originale else "assente"
    if not settore_originale:
        dedotti = deduce_settore(rec.get("descrizione"), categorie_clean)
        if dedotti:
            settore_dedotto = dedotti
            settore_fonte = "dedotto_keyword"

    settore_effettivo = settore_originale or (", ".join(settore_dedotto) if settore_dedotto else None)
    livello, label, emoji = compute_completezza(
        settore_effettivo, categorie_clean, rec.get("regione"), rec.get("descrizione")
    )

    cleaned = dict(rec)
    cleaned["categoria_mecspe_raw"] = rec.get("categoria_mecspe")  # traccia il valore originale per trasparenza
    cleaned["categoria_mecspe"] = categorie_clean
    cleaned["settore_dedotto"] = settore_dedotto
    cleaned["settore_fonte"] = settore_fonte
    cleaned["completezza_livello"] = livello
    cleaned["completezza_label"] = label
    cleaned["completezza_emoji"] = emoji
    return cleaned


def main():
    parser = argparse.ArgumentParser(description="Pulizia e normalizzazione del database aziende.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)

    print(f"Lettura di {len(data)} record da {args.input}")
    cleaned = [clean_record(r) for r in data]

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)

    # --- Report riassuntivo ---
    n_settore_originale = sum(1 for r in cleaned if r["settore_fonte"] == "originale")
    n_settore_dedotto = sum(1 for r in cleaned if r["settore_fonte"] == "dedotto_keyword")
    n_settore_assente = sum(1 for r in cleaned if r["settore_fonte"] == "assente")
    completezza_counts = Counter(r["completezza_label"] for r in cleaned)
    categoria_counts = Counter()
    for r in cleaned:
        for c in r["categoria_mecspe"]:
            categoria_counts[c] += 1

    print()
    print("=== REPORT PULIZIA ===")
    print(f"Record totali: {len(cleaned)}")
    print()
    print("--- Settore ---")
    print(f"  Originale presente: {n_settore_originale}")
    print(f"  Dedotto da keyword:  {n_settore_dedotto}")
    print(f"  Assente:             {n_settore_assente}")
    print()
    print("--- Completezza record ---")
    for label in ["ricca", "parziale", "scarsa", "solo_nome"]:
        print(f"  {label}: {completezza_counts.get(label, 0)}")
    print()
    print("--- Categorie MECSPE normalizzate (13 canoniche attese) ---")
    for cat, cnt in categoria_counts.most_common():
        print(f"  {cnt:5d}  |  {cat}")
    print()
    print(f"File pulito salvato in: {args.output}")


if __name__ == "__main__":
    main()
