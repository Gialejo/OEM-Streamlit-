"""
enrichment.py
Logica di arricchimento dati tramite:
- Gemini API (con Google Search grounding) -> classificazione OEM/RIVENDITORE/END_USER/
  DA_VERIFICARE, provincia/citta/sito web, descrizione aggiornata, motivazione, fonti.
- YouTube Data API v3 -> video rilevanti sull'azienda.

Tutte le chiamate sono racchiuse in try/except: un errore su una singola azienda
non deve mai far crashare l'arricchimento massivo delle altre.
"""

import json
import os
import re

import requests
import streamlit as st
from google import genai
from google.genai import types

GEMINI_MODEL = "gemini-3.5-flash"  # modello Gemini stabile e economico (aggiornalo qui se Google lo cambia in futuro)
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_MAX_RESULTS = 3


def get_secret(key: str) -> str | None:
    """Legge una chiave prima da st.secrets (utile in locale, con secrets.toml),
    poi da os.environ (utile su Render, dove le chiavi sono variabili d'ambiente
    e non esiste alcun file secrets.toml nel repository)."""
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key)


# --------------------------------------------------------------------------
# Client Gemini (cache_resource: una sola istanza per sessione del server)
# --------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_gemini_client():
    api_key = get_secret("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY mancante (né in st.secrets né nelle variabili d'ambiente)")
    return genai.Client(api_key=api_key)


def _extract_json(text: str) -> dict:
    """Estrae un oggetto JSON dalla risposta testuale del modello, tollerando
    eventuali code fence ```json ... ``` o testo extra prima/dopo."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(json)?", "", cleaned.strip(), flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"```$", "", cleaned.strip()).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Nessun JSON trovato nella risposta del modello: {text[:200]}")
    return json.loads(cleaned[start:end + 1])


PROMPT_TEMPLATE = """Sei un analista esperto del settore automazione industriale in Italia.
Ti fornisco il nome di un'azienda italiana e alcuni dati grezzi trovati online tramite scraping.

IMPORTANTE - definizione di OEM in questo contesto: un OEM è un'azienda che PROGETTA E
COSTRUISCE macchinari o impianti automatici completi per l'automazione industriale
(macchine automatiche, linee di produzione, isole robotizzate, ecc.), NON chi si limita
a vendere/distribuire macchine costruite da altri, e NON chi produce solo singoli
componenti o sub-forniture per conto terzi.

Il tuo compito:
1. Cerca sul web informazioni aggiornate e affidabili sull'azienda (sito ufficiale, sede,
   attivita' reale).
2. Classifica l'azienda in ESATTAMENTE una di queste categorie:
   - "OEM": costruisce macchinari/impianti automatici completi come propria attivita' principale.
   - "RIVENDITORE": vende, distribuisce o rappresenta macchinari/prodotti costruiti da altri.
   - "END_USER": produce componenti/sub-forniture oppure USA macchinari di automazione nel
     proprio processo produttivo, senza costruire macchine complete per conto terzi.
   - "DA_VERIFICARE": informazioni insufficienti per essere certi.
3. Scrivi una mini-descrizione aggiornata (massimo 300 caratteri, in italiano, professionale)
   di cosa fa realmente l'azienda.
4. Se riesci a trovarli, indica provincia, citta' della sede principale e sito web ufficiale.
5. Spiega in massimo 200 caratteri il motivo della classificazione.

Dati di partenza:
- Nome azienda: {nome}
- Regione (se nota, puo' essere vuota): {regione}
- Descrizione grezza trovata online: {descrizione}
- Categoria fiera/tag non affidabile (se nota): {categoria_mecspe}

Rispondi SOLO con un oggetto JSON valido, nessun testo prima o dopo, in questo formato esatto:
{{
  "categoria": "OEM|RIVENDITORE|END_USER|DA_VERIFICARE",
  "descrizione_ai": "...",
  "motivazione": "...",
  "provincia": "...",
  "citta": "...",
  "sito_web": "..."
}}
"""


def enrich_with_gemini(nome: str, regione: str | None, descrizione: str | None,
                        categoria_mecspe: str | None) -> dict:
    """Chiama Gemini con Google Search grounding attivo per classificare l'azienda
    e trovare dati aggiornati. Ritorna un dict pronto per db.update_enrichment
    (senza i campi youtube_videos, aggiunti separatamente)."""
    client = get_gemini_client()

    prompt = PROMPT_TEMPLATE.format(
        nome=nome or "",
        regione=regione or "non nota",
        descrizione=(descrizione or "nessuna descrizione disponibile")[:800],
        categoria_mecspe=categoria_mecspe or "nessuna",
    )

    grounding_tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(tools=[grounding_tool], temperature=0.2)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=config,
    )

    parsed = _extract_json(response.text)

    # Estrae le fonti usate dal grounding, se disponibili
    fonti = []
    try:
        candidate = response.candidates[0]
        gm = getattr(candidate, "grounding_metadata", None)
        if gm and getattr(gm, "grounding_chunks", None):
            for chunk in gm.grounding_chunks:
                web = getattr(chunk, "web", None)
                if web and getattr(web, "uri", None):
                    fonti.append({"titolo": getattr(web, "title", "") or "", "url": web.uri})
    except Exception:
        pass

    categoria = (parsed.get("categoria") or "DA_VERIFICARE").strip().upper()
    if categoria not in ("OEM", "RIVENDITORE", "END_USER", "DA_VERIFICARE"):
        categoria = "DA_VERIFICARE"

    return {
        "categoria_oem": categoria,
        "descrizione_ai": parsed.get("descrizione_ai"),
        "motivazione": parsed.get("motivazione"),
        "provincia": parsed.get("provincia") or None,
        "citta": parsed.get("citta") or None,
        "sito_web": parsed.get("sito_web") or None,
        "fonti": fonti,
    }


def search_youtube(nome: str) -> list[dict]:
    """Cerca video rilevanti su YouTube per l'azienda. Ritorna lista di dict
    {title, url, thumbnail, channel}. Ritorna lista vuota in caso di errore/quota
    esaurita, senza sollevare eccezioni verso il chiamante."""
    api_key = get_secret("YOUTUBE_API_KEY")
    if not api_key:
        return []

    query = f"{nome} automazione industriale macchina automatica"
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": YOUTUBE_MAX_RESULTS,
        "key": api_key,
        "relevanceLanguage": "it",
        "regionCode": "IT",
        "safeSearch": "none",
    }
    try:
        resp = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=15)
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except Exception:
        return []

    videos = []
    for item in items:
        video_id = item.get("id", {}).get("videoId")
        snippet = item.get("snippet", {})
        if not video_id:
            continue
        videos.append({
            "title": snippet.get("title"),
            "channel": snippet.get("channelTitle"),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
        })
    return videos


def enrich_azienda(azienda: dict) -> dict:
    """Orchestratore: arricchisce una singola azienda con Gemini + YouTube.
    'azienda' e' un dict come restituito da db.get_by_id / riga del DataFrame."""
    categoria_mecspe = azienda.get("categoria_mecspe")
    if categoria_mecspe and isinstance(categoria_mecspe, str):
        try:
            categoria_mecspe_list = json.loads(categoria_mecspe)
            categoria_mecspe = ", ".join(categoria_mecspe_list)
        except Exception:
            pass

    gemini_data = enrich_with_gemini(
        nome=azienda.get("nome"),
        regione=azienda.get("regione"),
        descrizione=azienda.get("descrizione_originale"),
        categoria_mecspe=categoria_mecspe,
    )

    videos = search_youtube(azienda.get("nome"))
    gemini_data["youtube_videos"] = videos
    return gemini_data
