"""
db.py
Gestione del database SQLite per l'app OEM Explorer Italia.

Schema tabella "aziende":
- id                 : id originale dal JSON sorgente (PRIMARY KEY)
- nome                (Ragione Sociale)
- settore             (settore originale, dal JSON sorgente)
- settore_dedotto     (JSON stringificato: lista settori dedotti da keyword quando settore e' assente)
- settore_fonte       ("originale" | "dedotto_keyword" | "assente")
- categoria_mecspe    (JSON stringificato, lista di categorie MECSPE gia' normalizzate)
- regione
- descrizione_originale (Mini Descrizione grezza da scraping)
- completezza_livello (0=ricca .. 3=solo nome, calcolato da clean_database.py)
- completezza_label   ("ricca" | "parziale" | "scarsa" | "solo_nome")
- provincia           (stimata via Gemini + Google Search grounding)
- citta
- sito_web
- categoria_oem       ("OEM" | "RIVENDITORE" | "END_USER" | "DA_VERIFICARE" | None)
- descrizione_ai      (mini-descrizione aggiornata generata da Gemini)
- motivazione         (spiegazione della classificazione)
- fonti               (JSON stringificato: URL usati da Gemini per il grounding)
- youtube_videos      (JSON stringificato: lista di {title, url, thumbnail, channel})
- arricchito          (0/1)
- arricchito_il       (timestamp ISO)

Nota: il file sorgente e' data/database_aziende_clean.json, gia' normalizzato
da clean_database.py (vedi quello script per la tassonomia categoria_mecspe
e la logica di deduzione settore/completezza). Un JSON caricato manualmente
dalla UI ("Carica/aggiorna JSON") dovrebbe essere gia' passato per quello
script, altrimenti categoria_mecspe/settore_dedotto/completezza non saranno
normalizzati.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

from search import compute_relevance

DB_PATH = Path(__file__).parent / "data" / "aziende.db"
SOURCE_JSON_PATH = Path(__file__).parent / "data" / "database_aziende_clean.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS aziende (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    settore TEXT,
    settore_dedotto TEXT,
    settore_fonte TEXT,
    categoria_mecspe TEXT,
    regione TEXT,
    descrizione_originale TEXT,
    completezza_livello INTEGER,
    completezza_label TEXT,
    provincia TEXT,
    citta TEXT,
    sito_web TEXT,
    categoria_oem TEXT,
    descrizione_ai TEXT,
    motivazione TEXT,
    fonti TEXT,
    youtube_videos TEXT,
    arricchito INTEGER DEFAULT 0,
    arricchito_il TEXT
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Crea il DB/tabella se non esistono e importa il JSON sorgente al primo avvio."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    first_time = not DB_PATH.exists()
    with get_conn() as conn:
        conn.execute(SCHEMA)
    if first_time and SOURCE_JSON_PATH.exists():
        import_json(SOURCE_JSON_PATH)


def import_json(file_or_path):
    """
    Importa/aggiorna aziende da un file JSON gia' passato per clean_database.py,
    con record del tipo:
    {"id": 1, "nome": "...", "settore": ..., "categoria_mecspe": [...],
     "regione": ..., "descrizione": "...", "settore_dedotto": [...] | null,
     "settore_fonte": "...", "completezza_livello": 0-3, "completezza_label": "..."}

    Fa un UPSERT sui campi "sorgente" (nome, settore, categoria_mecspe, regione,
    descrizione_originale, settore_dedotto, settore_fonte, completezza_*) senza
    toccare i campi gia' arricchiti (categoria_oem, descrizione_ai, ecc.), cosi'
    un ricaricamento del JSON non cancella il lavoro di arricchimento gia' fatto.
    """
    if hasattr(file_or_path, "read"):
        data = json.load(file_or_path)
    else:
        with open(file_or_path, "r", encoding="utf-8") as f:
            data = json.load(f)

    with get_conn() as conn:
        for rec in data:
            categoria_mecspe = rec.get("categoria_mecspe")
            categoria_mecspe_json = json.dumps(categoria_mecspe, ensure_ascii=False) if categoria_mecspe else None
            settore_dedotto = rec.get("settore_dedotto")
            settore_dedotto_json = json.dumps(settore_dedotto, ensure_ascii=False) if settore_dedotto else None
            conn.execute(
                """
                INSERT INTO aziende (
                    id, nome, settore, settore_dedotto, settore_fonte,
                    categoria_mecspe, regione, descrizione_originale,
                    completezza_livello, completezza_label
                )
                VALUES (
                    :id, :nome, :settore, :settore_dedotto, :settore_fonte,
                    :categoria_mecspe, :regione, :descrizione,
                    :completezza_livello, :completezza_label
                )
                ON CONFLICT(id) DO UPDATE SET
                    nome=excluded.nome,
                    settore=excluded.settore,
                    settore_dedotto=excluded.settore_dedotto,
                    settore_fonte=excluded.settore_fonte,
                    categoria_mecspe=excluded.categoria_mecspe,
                    regione=excluded.regione,
                    descrizione_originale=excluded.descrizione_originale,
                    completezza_livello=excluded.completezza_livello,
                    completezza_label=excluded.completezza_label
                """,
                {
                    "id": rec.get("id"),
                    "nome": rec.get("nome"),
                    "settore": rec.get("settore"),
                    "settore_dedotto": settore_dedotto_json,
                    "settore_fonte": rec.get("settore_fonte"),
                    "categoria_mecspe": categoria_mecspe_json,
                    "regione": rec.get("regione"),
                    "descrizione": rec.get("descrizione"),
                    "completezza_livello": rec.get("completezza_livello"),
                    "completezza_label": rec.get("completezza_label"),
                },
            )
    return len(data)


def get_stats() -> dict:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM aziende").fetchone()[0]
        arricchite = conn.execute("SELECT COUNT(*) FROM aziende WHERE arricchito=1").fetchone()[0]
        oem = conn.execute("SELECT COUNT(*) FROM aziende WHERE categoria_oem='OEM'").fetchone()[0]
        rivenditori = conn.execute("SELECT COUNT(*) FROM aziende WHERE categoria_oem='RIVENDITORE'").fetchone()[0]
        end_users = conn.execute("SELECT COUNT(*) FROM aziende WHERE categoria_oem='END_USER'").fetchone()[0]
        solo_nome = conn.execute("SELECT COUNT(*) FROM aziende WHERE completezza_label='solo_nome'").fetchone()[0]
    return {
        "total": total,
        "arricchite": arricchite,
        "oem": oem,
        "rivenditori": rivenditori,
        "end_users": end_users,
        "solo_nome": solo_nome,
    }


def get_filter_options() -> dict:
    with get_conn() as conn:
        regioni = [r[0] for r in conn.execute(
            "SELECT DISTINCT regione FROM aziende WHERE regione IS NOT NULL AND regione != '' ORDER BY regione"
        ).fetchall()]
        province = [r[0] for r in conn.execute(
            "SELECT DISTINCT provincia FROM aziende WHERE provincia IS NOT NULL AND provincia != '' ORDER BY provincia"
        ).fetchall()]
    return {"regioni": regioni, "province": province}


def get_dataframe(
    search: str = "",
    regioni: list | None = None,
    province: list | None = None,
    categorie_oem: list | None = None,
    ha_descrizione: bool | None = None,
    completezza_livelli: list | None = None,
    solo_da_arricchire: bool = False,
    limit: int = 500,
) -> pd.DataFrame:
    """
    Restituisce le aziende che soddisfano i filtri strutturati (regione,
    provincia, categoria OEM, presenza descrizione, completezza,
    stato arricchimento), applicati in SQL.

    Se 'search' e' valorizzato, il filtro testuale NON viene fatto in SQL:
    si carica il sottoinsieme gia' filtrato (al massimo ~3300 righe, che
    stanno comodamente in memoria) e si applica un ranking di rilevanza in
    Python tollerante ad accenti/typo e pesato su piu' campi (vedi
    search.compute_relevance), ordinando per rilevanza decrescente. Senza
    ricerca testuale l'ordinamento resta alfabetico per nome.
    """
    query = "SELECT * FROM aziende WHERE 1=1"
    params: list = []

    if regioni:
        query += f" AND regione IN ({','.join('?' * len(regioni))})"
        params += regioni

    if province:
        query += f" AND provincia IN ({','.join('?' * len(province))})"
        params += province

    if categorie_oem:
        placeholders = ",".join("?" * len(categorie_oem))
        if "NON_ARRICCHITO" in categorie_oem:
            others = [c for c in categorie_oem if c != "NON_ARRICCHITO"]
            if others:
                sub_ph = ",".join("?" * len(others))
                query += f" AND (categoria_oem IS NULL OR categoria_oem IN ({sub_ph}))"
                params += others
            else:
                query += " AND categoria_oem IS NULL"
        else:
            query += f" AND categoria_oem IN ({placeholders})"
            params += categorie_oem

    if ha_descrizione is True:
        query += " AND descrizione_originale IS NOT NULL AND descrizione_originale != ''"
    elif ha_descrizione is False:
        query += " AND (descrizione_originale IS NULL OR descrizione_originale = '')"

    if completezza_livelli:
        query += f" AND completezza_livello IN ({','.join('?' * len(completezza_livelli))})"
        params += completezza_livelli

    if solo_da_arricchire:
        query += " AND arricchito = 0"

    query += " ORDER BY nome ASC"
    if not search:
        query += " LIMIT ?"
        params.append(limit)

    with get_conn() as conn:
        df = pd.read_sql_query(query, conn, params=params)

    if search:
        df = _apply_smart_search(df, search, limit)

    return df


def _settore_display(row: pd.Series) -> str:
    if row.get("settore"):
        return row["settore"]
    if row.get("settore_dedotto"):
        try:
            return ", ".join(json.loads(row["settore_dedotto"]))
        except Exception:
            return ""
    return ""


def _apply_smart_search(df: pd.DataFrame, search: str, limit: int) -> pd.DataFrame:
    """Applica il ranking di rilevanza (search.compute_relevance) al dataframe
    gia' filtrato strutturalmente, tenendo solo i risultati pertinenti
    ordinati per punteggio decrescente."""
    if df.empty:
        return df

    scores = []
    for _, row in df.iterrows():
        record = {
            "nome": row.get("nome"),
            "descrizione_ai": row.get("descrizione_ai"),
            "descrizione_originale": row.get("descrizione_originale"),
            "settore_display": _settore_display(row),
            "provincia": row.get("provincia"),
            "citta": row.get("citta"),
        }
        scores.append(compute_relevance(record, search))

    df = df.assign(_relevance=scores)
    df = df[df["_relevance"] > 0].sort_values("_relevance", ascending=False)
    return df.drop(columns="_relevance").head(limit)


def get_by_id(azienda_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM aziende WHERE id = ?", (azienda_id,)).fetchone()
    return dict(row) if row else None


def update_enrichment(azienda_id: int, data: dict):
    """
    data puo' contenere: provincia, citta, sito_web, categoria_oem,
    descrizione_ai, motivazione, fonti (list), youtube_videos (list)
    """
    payload = {
        "id": azienda_id,
        "provincia": data.get("provincia"),
        "citta": data.get("citta"),
        "sito_web": data.get("sito_web"),
        "categoria_oem": data.get("categoria_oem"),
        "descrizione_ai": data.get("descrizione_ai"),
        "motivazione": data.get("motivazione"),
        "fonti": json.dumps(data.get("fonti") or [], ensure_ascii=False),
        "youtube_videos": json.dumps(data.get("youtube_videos") or [], ensure_ascii=False),
        "arricchito_il": datetime.utcnow().isoformat(),
    }
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE aziende SET
                provincia=:provincia,
                citta=:citta,
                sito_web=:sito_web,
                categoria_oem=:categoria_oem,
                descrizione_ai=:descrizione_ai,
                motivazione=:motivazione,
                fonti=:fonti,
                youtube_videos=:youtube_videos,
                arricchito=1,
                arricchito_il=:arricchito_il
            WHERE id=:id
            """,
            payload,
        )
