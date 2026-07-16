# 🏭 OEM Explorer Italia

App Streamlit per esplorare e arricchire con l'AI un database di aziende OEM
(costruttori di macchinari automatici) del settore automazione industriale in Italia.

## Funzionalità

- Import/aggiornamento database da file JSON (upsert, non perde i dati arricchiti)
- Tabella con ricerca full-text, filtri per Regione/Provincia/Categoria
- Selezione multipla righe → arricchimento **manuale, solo per le aziende selezionate**
  (nessun bottone "arricchisci tutte", per contenere tempi e quota API)
- Arricchimento tramite:
  - **Gemini API** con **Google Search grounding** attivo → classifica l'azienda come
    `OEM` / `RIVENDITORE` / `END_USER` / `DA_VERIFICARE`, stima provincia/città/sito
    web, riscrive la mini-descrizione, spiega la motivazione, salva le fonti usate
  - **YouTube Data API v3** → 3 video rilevanti sull'azienda
- Pagina di dettaglio con tutte le informazioni, badge colorati, video incorporati
- Dati persistiti in **SQLite** locale (`data/aziende.db`)

---

## 1. Struttura del progetto

```
oem-explorer/
├── app.py                        # App Streamlit (UI + routing)
├── db.py                         # Accesso SQLite (schema, import, query, update)
├── enrichment.py                 # Chiamate Gemini + YouTube Data API v3
├── requirements.txt
├── render.yaml                   # Config deploy Render
├── .gitignore
├── data/
│   └── database_aziende.json     # Dataset di partenza (import automatico al primo avvio)
└── .streamlit/
    ├── config.toml                # Tema Streamlit
    └── secrets.toml.example       # Template chiavi API (da copiare e compilare)
```

---

## 2. Setup in locale

### 2.1 Requisiti
- Python 3.10+
- Un account Google (per le API key)

### 2.2 Crea l'ambiente virtuale e installa le dipendenze

```bash
cd oem-explorer
python -m venv .venv
source .venv/bin/activate      # su Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2.3 Ottieni le API key

**Gemini API key**
1. Vai su [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Accedi con un account Google
3. Clicca "Create API key" e copiala

**YouTube Data API v3 key**
1. Vai su [Google Cloud Console](https://console.cloud.google.com/)
2. Crea un progetto (o usane uno esistente)
3. Vai su "API e servizi" → "Libreria", cerca **YouTube Data API v3** e abilitala
4. Vai su "Credenziali" → "Crea credenziali" → "Chiave API" e copiala
5. (Consigliato) Limita la chiave solo a "YouTube Data API v3" nelle restrizioni

> Nota quote: YouTube Data API v3 ha un limite gratuito di 10.000 unità/giorno;
> ogni chiamata `search` costa 100 unità (~100 aziende arricchibili al giorno
> con il piano gratuito). Se ti serve di più, valuta l'upgrade quota su Cloud Console.

### 2.4 Configura le chiavi in locale

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Apri `.streamlit/secrets.toml` e incolla le tue chiavi:

```toml
GEMINI_API_KEY = "AIza...la-tua-chiave-gemini"
YOUTUBE_API_KEY = "AIza...la-tua-chiave-youtube"
```

Questo file è già escluso da `.gitignore`: non verrà mai committato su GitHub.

### 2.5 Avvia l'app

```bash
streamlit run app.py
```

Al primo avvio, l'app crea `data/aziende.db` e importa automaticamente
`data/database_aziende.json` (3.390 aziende). Puoi anche ricaricare/aggiornare
il JSON in qualsiasi momento dalla sidebar ("📤 Carica / aggiorna JSON").

---

## 3. Pubblicare il codice su GitHub

```bash
git init
git add .
git commit -m "Prima versione OEM Explorer Italia"
git branch -M main
git remote add origin https://github.com/<tuo-utente>/oem-explorer.git
git push -u origin main
```

Verifica che `.streamlit/secrets.toml` **non** compaia tra i file committati
(deve comparire solo `secrets.toml.example`).

---

## 4. Deploy su Render

### Opzione A — con `render.yaml` (Blueprint, consigliata)

1. Vai su [Render](https://render.com) → **New** → **Blueprint**
2. Collega il repository GitHub `oem-explorer`
3. Render legge `render.yaml` e propone il servizio `oem-explorer` (Python, piano Free)
4. Nella schermata di setup, inserisci i valori per le env var richieste:
   - `GEMINI_API_KEY`
   - `YOUTUBE_API_KEY`
5. Clicca **Apply** / **Create Web Service**

### Opzione B — manuale

1. Vai su Render → **New** → **Web Service**
2. Collega il repo GitHub
3. Configura:
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`
4. In **Environment → Environment Variables**, aggiungi:
   - `GEMINI_API_KEY` = la tua chiave
   - `YOUTUBE_API_KEY` = la tua chiave
5. Crea il servizio

### Nota sulla persistenza dei dati (piano Free)

Il piano Free di Render ha filesystem **effimero**: ad ogni deploy o riavvio del
servizio, `data/aziende.db` viene ricreato da zero e reimportato dal JSON
originale, perdendo gli arricchimenti fatti fino a quel momento. Va bene per
uso/demo, ma se in futuro vuoi dati persistenti tra i deploy, le opzioni sono:
- aggiungere un **Persistent Disk** Render (piano a pagamento) montato su `data/`
- oppure migrare da SQLite a un database esterno gestito (es. Postgres su
  Supabase/Neon/Render Postgres)

---

## 5. Personalizzazioni rapide

- **Modello Gemini**: cambia `GEMINI_MODEL` in cima a `enrichment.py`
- **Numero video YouTube**: cambia `YOUTUBE_MAX_RESULTS` in `enrichment.py`
- **Colori/branding**: modifica `CUSTOM_CSS` in `app.py` e `.streamlit/config.toml`
- **Definizione OEM/RIVENDITORE/END_USER**: modifica `PROMPT_TEMPLATE` in
  `enrichment.py` se vuoi affinare i criteri di classificazione

---

## 6. Limiti noti / prossimi passi possibili

- Nessuna autenticazione utenti (app pensata per uso interno/team)
- L'arricchimento è solo manuale su selezione (per design, per controllare costi/tempi)
- La stima di provincia/città è "best effort" via grounding Gemini, non un
  geocoder ufficiale: per dati anagrafici certificati valuta in futuro un
  incrocio con Registro Imprese / VIES / Camera di Commercio
