"""
db.py
Gestione del database SQLite per l'app OEM Explorer Italia.

Schema tabella "aziende":
- id                 : id originale dal JSON sorgente (PRIMARY KEY)
- nome                (Ragione Sociale)
- settore
- categoria_mecspe    (JSON stringificato, lista di tag fiera)
- regione
- descrizione_originale (Mini Descrizione grezza da scraping)
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
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).parent / "data" / "aziende.db"
SOURCE_JSON_PATH = Path(__file__).parent / "data" / "database_aziende.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS aziende (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    settore TEXT,
    categoria_mecspe TEXT,
    regione TEXT,
    descrizione_originale TEXT,
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
    Importa/aggiorna aziende da un file JSON con record del tipo:
    {"id": 1, "nome": "...", "settore": ..., "categoria_mecspe": [...],
     "regione": ..., "descrizione": "..."}

    Fa un UPSERT sui campi "sorgente" (nome, settore, categoria_mecspe, regione,
    descrizione_originale) senza toccare i campi già arricchiti, cosi' un
    ricaricamento del JSON non cancella il lavoro di arricchimento già fatto.
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
            conn.execute(
                """
                INSERT INTO aziende (id, nome, settore, categoria_mecspe, regione, descrizione_originale)
                VALUES (:id, :nome, :settore, :categoria_mecspe, :regione, :descrizione)
                ON CONFLICT(id) DO UPDATE SET
                    nome=excluded.nome,
                    settore=excluded.settore,
                    categoria_mecspe=excluded.categoria_mecspe,
                    regione=excluded.regione,
                    descrizione_originale=excluded.descrizione_originale
                """,
                {
                    "id": rec.get("id"),
                    "nome": rec.get("nome"),
                    "settore": rec.get("settore"),
                    "categoria_mecspe": categoria_mecspe_json,
                    "regione": rec.get("regione"),
                    "descrizione": rec.get("descrizione"),
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
    return {
        "total": total,
        "arricchite": arricchite,
        "oem": oem,
        "rivenditori": rivenditori,
        "end_users": end_users,
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
    solo_da_arricchire: bool = False,
    limit: int = 500,
) -> pd.DataFrame:
    query = "SELECT * FROM aziende WHERE 1=1"
    params: list = []

    if search:
        query += " AND (nome LIKE ? OR descrizione_originale LIKE ? OR descrizione_ai LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like]

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

    if solo_da_arricchire:
        query += " AND arricchito = 0"

    query += " ORDER BY nome ASC LIMIT ?"
    params.append(limit)

    with get_conn() as conn:
        df = pd.read_sql_query(query, conn, params=params)
    return df


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
