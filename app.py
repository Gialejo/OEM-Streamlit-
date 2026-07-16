"""
OEM Explorer Italia
Streamlit app per esplorare e arricchire (Gemini + YouTube Data API v3) un
database di aziende del settore automazione industriale in Italia.
"""

import json
import time

import pandas as pd
import streamlit as st

import db
from enrichment import enrich_azienda

# --------------------------------------------------------------------------
# Config pagina + CSS
# --------------------------------------------------------------------------
st.set_page_config(
    page_title="OEM Explorer Italia",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

CATEGORY_STYLE = {
    "OEM": {"emoji": "🟢", "label": "OEM", "color": "#16a34a", "bg": "#dcfce7"},
    "RIVENDITORE": {"emoji": "🟠", "label": "Rivenditore", "color": "#c2410c", "bg": "#ffedd5"},
    "END_USER": {"emoji": "🔵", "label": "End user", "color": "#1d4ed8", "bg": "#dbeafe"},
    "DA_VERIFICARE": {"emoji": "⚪", "label": "Da verificare", "color": "#525252", "bg": "#f4f4f5"},
    None: {"emoji": "⬜", "label": "Non arricchito", "color": "#9ca3af", "bg": "#fafafa"},
}

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"]  {
    font-family: 'Inter', sans-serif;
}

.main .block-container {
    padding-top: 1.5rem;
    max-width: 1300px;
}

.oem-hero {
    background: linear-gradient(120deg, #0f172a 0%, #1e3a5f 60%, #0ea5a4 130%);
    padding: 28px 32px;
    border-radius: 16px;
    color: white;
    margin-bottom: 1.4rem;
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.25);
}
.oem-hero h1 {
    margin: 0;
    font-size: 1.9rem;
    font-weight: 800;
    letter-spacing: -0.02em;
}
.oem-hero p {
    margin: 6px 0 0 0;
    opacity: 0.85;
    font-size: 0.95rem;
}

.metric-card {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    padding: 14px 18px;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.metric-card .value {
    font-size: 1.6rem;
    font-weight: 800;
    color: #0f172a;
}
.metric-card .label {
    font-size: 0.78rem;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

.pill {
    display: inline-block;
    padding: 3px 12px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 700;
}

.detail-card {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 14px;
    padding: 22px 26px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    margin-bottom: 16px;
}

.video-card {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 10px;
}
.video-card img {
    width: 100%;
    display: block;
}
.video-card .vtitle {
    padding: 8px 10px 2px 10px;
    font-size: 0.85rem;
    font-weight: 600;
    color: #111827;
}
.video-card .vchannel {
    padding: 0 10px 10px 10px;
    font-size: 0.75rem;
    color: #6b7280;
}

section[data-testid="stSidebar"] {
    background: #0f172a;
}
section[data-testid="stSidebar"] * {
    color: #e5e7eb !important;
}
section[data-testid="stSidebar"] .stTextInput input,
section[data-testid="stSidebar"] .stMultiSelect div[data-baseweb="select"] {
    color: #111827 !important;
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def pill_html(categoria: str | None) -> str:
    s = CATEGORY_STYLE.get(categoria, CATEGORY_STYLE[None])
    return f'<span class="pill" style="background:{s["bg"]};color:{s["color"]}">{s["emoji"]} {s["label"]}</span>'


# --------------------------------------------------------------------------
# Init DB + session state
# --------------------------------------------------------------------------
db.init_db()

if "page" not in st.session_state:
    st.session_state.page = "list"
if "selected_id" not in st.session_state:
    st.session_state.selected_id = None


def go_to_detail(azienda_id: int):
    st.session_state.selected_id = azienda_id
    st.session_state.page = "detail"


def go_to_list():
    st.session_state.page = "list"
    st.session_state.selected_id = None


# --------------------------------------------------------------------------
# Sidebar: caricamento dati + filtri
# --------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🏭 OEM Explorer")
    st.caption("Aziende OEM automazione industriale — Italia")

    with st.expander("📤 Carica / aggiorna JSON", expanded=False):
        uploaded = st.file_uploader("File JSON aziende", type=["json"])
        if uploaded is not None:
            if st.button("Importa nel database", use_container_width=True):
                n = db.import_json(uploaded)
                st.success(f"Importati/aggiornati {n} record.")
                st.rerun()
        st.caption(
            "L'import fa un upsert per `id`: i campi già arricchiti "
            "(categoria, descrizione AI, video) non vengono sovrascritti."
        )

    st.markdown("---")
    st.markdown("#### 🔎 Filtri")
    search = st.text_input("Cerca per nome o descrizione", value="", placeholder="es. saldatura, packaging, robot...")

    filter_opts = db.get_filter_options()
    regioni_sel = st.multiselect("Regione", options=filter_opts["regioni"])
    province_sel = st.multiselect("Provincia", options=filter_opts["province"])

    categorie_labels = {
        "OEM": "🟢 OEM",
        "RIVENDITORE": "🟠 Rivenditore",
        "END_USER": "🔵 End user",
        "DA_VERIFICARE": "⚪ Da verificare",
        "NON_ARRICCHITO": "⬜ Non arricchito",
    }
    categorie_sel_labels = st.multiselect(
        "Categoria",
        options=list(categorie_labels.values()),
    )
    inv_labels = {v: k for k, v in categorie_labels.items()}
    categorie_sel = [inv_labels[lbl] for lbl in categorie_sel_labels]

    solo_da_arricchire = st.checkbox("Mostra solo aziende NON arricchite", value=False)

    limit = st.slider("Righe massime da mostrare", min_value=50, max_value=2000, value=500, step=50)

    st.markdown("---")
    stats = db.get_stats()
    st.markdown("#### 📊 Statistiche")
    c1, c2 = st.columns(2)
    c1.metric("Totale aziende", stats["total"])
    c2.metric("Arricchite", stats["arricchite"])
    c1.metric("🟢 OEM", stats["oem"])
    c2.metric("🟠 Rivenditori", stats["rivenditori"])
    st.metric("🔵 End user", stats["end_users"])


# --------------------------------------------------------------------------
# PAGINA: LISTA
# --------------------------------------------------------------------------
def render_list_page():
    st.markdown(
        """
        <div class="oem-hero">
            <h1>🏭 OEM Explorer Italia</h1>
            <p>Esplora, filtra e arricchisci con l'AI il database di aziende OEM del settore automazione industriale.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    df = db.get_dataframe(
        search=search,
        regioni=regioni_sel or None,
        province=province_sel or None,
        categorie_oem=categorie_sel or None,
        solo_da_arricchire=solo_da_arricchire,
        limit=limit,
    )

    if df.empty:
        st.info("Nessuna azienda trovata con i filtri correnti.")
        return

    display_df = pd.DataFrame({
        "id": df["id"],
        "Nome": df["nome"],
        "Regione": df["regione"].fillna("—"),
        "Provincia": df["provincia"].fillna("—"),
        "Categoria": df["categoria_oem"].map(lambda c: CATEGORY_STYLE.get(c, CATEGORY_STYLE[None])["emoji"] + " " + CATEGORY_STYLE.get(c, CATEGORY_STYLE[None])["label"]),
        "Descrizione": df["descrizione_ai"].fillna(df["descrizione_originale"]).fillna("").str.slice(0, 140),
        "Arricchito": df["arricchito"].map(lambda x: "✅" if x == 1 else "⬜"),
    })

    st.caption(f"{len(df)} aziende visualizzate (limite impostato: {limit}).")

    event = st.dataframe(
        display_df,
        hide_index=True,
        use_container_width=True,
        height=460,
        column_config={
            "id": None,  # nascosto
            "Descrizione": st.column_config.TextColumn(width="large"),
        },
        on_select="rerun",
        selection_mode="multi-row",
        key="main_table",
    )

    selected_positions = event.selection.rows if event and event.selection else []
    selected_ids = df.iloc[selected_positions]["id"].tolist() if selected_positions else []

    col_a, col_b, col_c = st.columns([2, 2, 4])
    with col_a:
        enrich_clicked = st.button(
            f"✨ Arricchisci selezionate ({len(selected_ids)})",
            type="primary",
            disabled=len(selected_ids) == 0,
            use_container_width=True,
        )
    with col_b:
        detail_clicked = st.button(
            "🔍 Vedi dettaglio",
            disabled=len(selected_ids) != 1,
            use_container_width=True,
        )
    with col_c:
        if len(selected_ids) == 0:
            st.caption("Seleziona una o più righe dalla tabella (checkbox a sinistra) per arricchirle o vedere il dettaglio.")

    if detail_clicked and len(selected_ids) == 1:
        go_to_detail(selected_ids[0])
        st.rerun()

    if enrich_clicked and selected_ids:
        progress = st.progress(0.0, text="Avvio arricchimento...")
        log_area = st.empty()
        errors = []
        for i, azienda_id in enumerate(selected_ids, start=1):
            azienda = db.get_by_id(azienda_id)
            progress.progress(i / len(selected_ids), text=f"Arricchimento: {azienda['nome']} ({i}/{len(selected_ids)})")
            try:
                result = enrich_azienda(azienda)
                db.update_enrichment(azienda_id, result)
                log_area.write(f"✅ {azienda['nome']} → {result.get('categoria_oem')}")
            except Exception as e:
                errors.append((azienda["nome"], str(e)))
                log_area.write(f"❌ {azienda['nome']} → errore: {e}")
            time.sleep(0.3)  # piccola pausa anti rate-limit

        progress.progress(1.0, text="Completato.")
        if errors:
            st.warning(f"{len(errors)} aziende non arricchite per errore. Controlla le API key e le quote.")
        else:
            st.success("Arricchimento completato per tutte le aziende selezionate.")
        st.rerun()


# --------------------------------------------------------------------------
# PAGINA: DETTAGLIO
# --------------------------------------------------------------------------
def render_detail_page():
    azienda = db.get_by_id(st.session_state.selected_id)
    if azienda is None:
        st.error("Azienda non trovata.")
        if st.button("← Torna alla lista"):
            go_to_list()
            st.rerun()
        return

    if st.button("← Torna alla lista"):
        go_to_list()
        st.rerun()

    categoria = azienda.get("categoria_oem")
    style = CATEGORY_STYLE.get(categoria, CATEGORY_STYLE[None])

    st.markdown(
        f"""
        <div class="oem-hero">
            <h1>{azienda['nome']}</h1>
            <p>{pill_html(categoria)} &nbsp;·&nbsp; {azienda.get('regione') or '—'} / {azienda.get('provincia') or '—'} {(' · ' + azienda['citta']) if azienda.get('citta') else ''}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown('<div class="detail-card">', unsafe_allow_html=True)
        st.markdown("#### 📝 Descrizione aggiornata (AI)")
        if azienda.get("descrizione_ai"):
            st.write(azienda["descrizione_ai"])
        else:
            st.info("Non ancora arricchita. Torna alla lista, seleziona l'azienda e premi 'Arricchisci selezionate'.")

        st.markdown("#### 📄 Descrizione originale (scraping)")
        st.write(azienda.get("descrizione_originale") or "—")

        if azienda.get("motivazione"):
            st.markdown("#### 🧠 Motivazione classificazione AI")
            st.write(azienda["motivazione"])
        st.markdown('</div>', unsafe_allow_html=True)

        # Video YouTube
        videos = json.loads(azienda.get("youtube_videos") or "[]")
        if videos:
            st.markdown("#### 🎬 Video rilevanti")
            vcols = st.columns(len(videos))
            for vcol, video in zip(vcols, videos):
                with vcol:
                    thumb = f'<img src="{video.get("thumbnail", "")}">' if video.get("thumbnail") else ""
                    st.markdown(
                        f"""
                        <a href="{video.get('url')}" target="_blank" style="text-decoration:none;">
                        <div class="video-card">
                            {thumb}
                            <div class="vtitle">{video.get('title', '')}</div>
                            <div class="vchannel">{video.get('channel', '')}</div>
                        </div>
                        </a>
                        """,
                        unsafe_allow_html=True,
                    )

    with col2:
        st.markdown('<div class="detail-card">', unsafe_allow_html=True)
        st.markdown("#### ℹ️ Informazioni")
        st.markdown(f"**Settore:** {azienda.get('settore') or '—'}")
        cat_mecspe = azienda.get("categoria_mecspe")
        if cat_mecspe:
            try:
                cat_mecspe = ", ".join(json.loads(cat_mecspe))
            except Exception:
                pass
        st.markdown(f"**Categoria fiera (MECSPE):** {cat_mecspe or '—'}")
        st.markdown(f"**Regione:** {azienda.get('regione') or '—'}")
        st.markdown(f"**Provincia:** {azienda.get('provincia') or '—'}")
        st.markdown(f"**Città:** {azienda.get('citta') or '—'}")
        if azienda.get("sito_web"):
            st.markdown(f"**Sito web:** [{azienda['sito_web']}]({azienda['sito_web']})")
        else:
            st.markdown("**Sito web:** —")
        st.markdown(
            f"**Stato arricchimento:** {'✅ Arricchita il ' + azienda['arricchito_il'][:10] if azienda.get('arricchito') else '⬜ Non arricchita'}"
        )
        st.markdown('</div>', unsafe_allow_html=True)

        fonti = json.loads(azienda.get("fonti") or "[]")
        if fonti:
            st.markdown('<div class="detail-card">', unsafe_allow_html=True)
            st.markdown("#### 🔗 Fonti (Google Search grounding)")
            for f in fonti:
                st.markdown(f"- [{f.get('titolo') or f.get('url')}]({f.get('url')})")
            st.markdown('</div>', unsafe_allow_html=True)

        if st.button("🔄 Ri-arricchisci questa azienda", use_container_width=True):
            with st.spinner("Arricchimento in corso..."):
                try:
                    result = enrich_azienda(azienda)
                    db.update_enrichment(azienda["id"], result)
                    st.success("Arricchimento aggiornato.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore durante l'arricchimento: {e}")


# --------------------------------------------------------------------------
# Router
# --------------------------------------------------------------------------
if st.session_state.page == "detail" and st.session_state.selected_id is not None:
    render_detail_page()
else:
    render_list_page()
