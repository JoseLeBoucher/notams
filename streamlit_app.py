"""
NOTAM Brief — version Streamlit (hébergement gratuit sur Streamlit Community Cloud).

Déploiement :
    1. Crée un dépôt GitHub contenant ce dossier (streamlit_app.py, notam_parser.py,
       requirements.txt).
    2. Va sur share.streamlit.io, connecte ton compte GitHub, choisis le dépôt et
       indique streamlit_app.py comme fichier principal.
    3. L'URL obtenue s'ouvre dans Safari sur l'iPad.

Aucune donnée n'est stockée côté serveur : les bulletins sont collés ou importés à
chaque session et restent dans la session du navigateur.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import streamlit as st

from notam_parser import ORDRE_ROLE, ROLE_PAR_SECTION, Row, decouper_bulletins, parse_bulletin

st.set_page_config(page_title="NOTAM Brief", page_icon="🛫", layout="wide")

# --------------------------------------------------------------------------- #
# Style
# --------------------------------------------------------------------------- #

PALETTE_CAT = {
    "RUNWAY":             ("#8e1c1c", "#fae9e5"),
    "APPROACH PROCEDURE": ("#0d3f8a", "#e6edf9"),
    "AIRPORT":            ("#15571b", "#e6f1e3"),
    "COMPANY NOTAM":      ("#5a2472", "#f2eaf6"),
}
PALETTE_DEFAUT = ("#37474f", "#ebe7dd")
STATUT = {
    "actif":  ("#0f5132", "#d8e9dc", "ACTIF"),
    "futur":  ("#664d03", "#fbf0d4", "À VENIR"),
    "expire": ("#6c757d", "#eae6dc", "EXPIRÉ"),
}

CSS = """
<style>
  .nb-band{margin:26px 0 0;padding:11px 14px;border-radius:9px;background:#1c2b3a;
    color:#fff;font-weight:600;font-size:15px;letter-spacing:.09em;text-transform:uppercase}
  .nb-aero{margin:22px 0 6px;padding-bottom:8px;border-bottom:2px solid #c7bfae}
  .nb-aero h2{margin:0;font-size:20px;font-weight:600}
  .nb-aero code{font-family:ui-monospace,Menlo,monospace;font-size:19px}
  .nb-aero .name{font-size:15px;font-weight:400;color:#4a5c6c;margin-left:10px}
  .nb-roles{margin-top:5px;font-size:12.5px;color:#0b5cab;font-family:ui-monospace,monospace}
  .nb-cat{margin:18px 0 0;padding:6px 12px;border-radius:7px;font-size:12px;font-weight:600;
    letter-spacing:.09em;text-transform:uppercase}
  .nb-notam{margin:12px 0 0;padding:12px 14px;background:#fdfbf6;border:1px solid #ddd7ca;
    border-radius:11px;border-left:3px solid #c7bfae}
  .nb-head{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-bottom:7px}
  .nb-id{font-family:ui-monospace,Menlo,monospace;font-weight:600;font-size:14.5px;color:#1f2933}
  .nb-pill{font-size:10.5px;font-weight:700;letter-spacing:.07em;padding:3px 8px;border-radius:999px}
  .nb-val{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;color:#55606b}
  .nb-tag{font-size:11.5px;color:#0b5cab;background:#e3ecf7;padding:2px 8px;border-radius:999px}
  .nb-body{font-family:ui-monospace,Menlo,monospace;font-size:13px;line-height:1.55;
    white-space:pre-wrap;margin:0;color:#1f2933}
  .nb-meta{margin-top:7px;font-family:ui-monospace,Menlo,monospace;font-size:11.5px;color:#7a8794;
    white-space:pre-wrap}
  .nb-mark{background:#fbe0da;color:#c0272d;font-weight:700;padding:0 2px;border-radius:3px}
</style>
"""

# --------------------------------------------------------------------------- #
# État de session
# --------------------------------------------------------------------------- #

DEFAUT_REGLES = "LPV, MINIMA\nCRANE\nVOR, UNSERVICEABLE"
DEFAUT_MARQUES = "CLSD, CLOSED, U/S, UNSERVICEABLE"


def init_etat():
    st.session_state.setdefault("bulletins", [])      # [{label, dep, dest, rows}]
    st.session_state.setdefault("regles_txt", "")     # une règle par ligne, mots séparés par virgule
    st.session_state.setdefault("marques_txt", DEFAUT_MARQUES)


def ajouter_texte(brut: str) -> int:
    """Ajoute un ou plusieurs bulletins collés. Retourne le nombre de vols ajoutés."""
    ajoutes = 0
    for part in decouper_bulletins(brut):
        b = parse_bulletin(part)
        if not b.rows:
            continue
        label = b.callsign or (f"{b.dep}→{b.dest}" if b.dep and b.dest
                               else f"Vol {len(st.session_state.bulletins) + 1}")
        for r in b.rows:
            r.source = label
        st.session_state.bulletins.append(
            {"label": label, "dep": b.dep or "?", "dest": b.dest or "?", "rows": b.rows})
        ajoutes += 1
    return ajoutes


# --------------------------------------------------------------------------- #
# Fusion + déduplication
# --------------------------------------------------------------------------- #

@dataclass
class Fusion:
    rows: list[Row]
    sources: dict[tuple[str, str], list[str]]
    roles: dict[str, dict[str, list[str]]]
    role_principal: dict[str, str]
    doublons: int


def fusionner(bulletins) -> Fusion:
    """Déduplique sur (terrain, ID NOTAM) : un NOTAM revu d'un vol à l'autre sur le
    même terrain n'apparaît qu'une fois, mais un NOTAM rattaché à deux terrains
    différents reste visible sous chacun."""
    vus: dict[tuple[str, str], Row] = {}
    sources: dict[tuple[str, str], list[str]] = {}
    roles: dict[str, dict[str, list[str]]] = {}
    ordre_aero: dict[str, int] = {}
    ordre_cat: dict[str, int] = {}
    doublons = 0

    for b in bulletins:
        for r in b["rows"]:
            vols = roles.setdefault(r.icao, {}).setdefault(r.role, [])
            if b["label"] not in vols:
                vols.append(b["label"])
            ordre_aero.setdefault(r.icao, len(ordre_aero))
            ordre_cat.setdefault(r.categorie, len(ordre_cat))
            if r.cle in vus:
                doublons += 1
                if b["label"] not in sources[r.cle]:
                    sources[r.cle].append(b["label"])
                continue
            vus[r.cle] = r
            sources[r.cle] = [b["label"]]

    principal = {ic: min(rr, key=ORDRE_ROLE.index) for ic, rr in roles.items()}
    rows = sorted(vus.values(),
                  key=lambda r: (ORDRE_ROLE.index(principal[r.icao]),
                                 ordre_aero[r.icao], ordre_cat[r.categorie]))
    return Fusion(rows, sources, roles, principal, doublons)


# --------------------------------------------------------------------------- #
# Filtres
# --------------------------------------------------------------------------- #

def lire_regles(txt: str) -> list[list[str]]:
    """Une règle par ligne ; mots séparés par des virgules (ET à l'intérieur d'une règle)."""
    regles = []
    for ligne in txt.splitlines():
        mots = [m.strip().upper() for m in ligne.replace(";", ",").split(",") if m.strip()]
        if mots:
            regles.append(mots)
    return regles


def regle_qui_masque(row: Row, regles: list[list[str]]) -> list[str] | None:
    return next((r for r in regles if all(m in row.texte for m in r)), None)


def surligner(texte: str, termes: list[str]) -> str:
    """Entoure les termes d'un span coloré, en échappant d'abord le HTML."""
    out = (texte.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    if not termes:
        return out
    motif = "|".join(re.escape(t) for t in termes if t)
    return re.sub(f"({motif})", r'<span class="nb-mark">\1</span>', out, flags=re.I)


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #

init_etat()
st.markdown(CSS, unsafe_allow_html=True)

with st.sidebar:
    st.header("Vols")
    with st.form("collage", clear_on_submit=True):
        colle = st.text_area("Coller un bulletin LIDO", height=150,
                             placeholder="Colle ici le bloc NOTAM d'un vol…")
        if st.form_submit_button("Ajouter", use_container_width=True):
            n = ajouter_texte(colle)
            st.toast(f"{n} vol(s) ajouté(s)" if n else "Aucun NOTAM reconnu dans ce texte.")

    fichiers = st.file_uploader("…ou importer des .txt", type=["txt"], accept_multiple_files=True)
    if fichiers:
        for f in fichiers:
            ajouter_texte(f.read().decode("utf-8", errors="replace"))
        st.session_state["_import_fait"] = True

    for i, b in enumerate(st.session_state.bulletins):
        c1, c2 = st.columns([5, 1])
        c1.caption(f"**{b['label']}** · {b['dep']} → {b['dest']} · {len(b['rows'])} NOTAM")
        if c2.button("×", key=f"del{i}", help="Retirer ce vol"):
            st.session_state.bulletins.pop(i)
            st.rerun()

    if st.session_state.bulletins and st.button("Tout retirer", use_container_width=True):
        st.session_state.bulletins = []
        st.rerun()

if not st.session_state.bulletins:
    st.title("NOTAM Brief")
    st.info("Colle le bloc NOTAM d'un vol depuis Lido dans le panneau de gauche, "
            "ou importe tes fichiers .txt. Plusieurs vols peuvent être chargés : "
            "les NOTAM déjà vus sur un même terrain ne seront affichés qu'une fois.")
    st.stop()

fus = fusionner(st.session_state.bulletins)
multi = len(st.session_state.bulletins) > 1

with st.sidebar:
    st.header("Filtres")
    icaos_dispo = list(dict.fromkeys(r.icao for r in fus.rows))
    libelle_icao = {ic: f"{ic} — {'/'.join(r for r in ORDRE_ROLE if r in fus.roles[ic])}"
                    for ic in icaos_dispo}
    icaos = st.multiselect("Terrain", icaos_dispo, default=icaos_dispo,
                           format_func=lambda ic: libelle_icao[ic])
    cats_dispo = sorted({r.categorie for r in fus.rows})
    cats = st.multiselect("Type de NOTAM", cats_dispo, default=cats_dispo)

    mode = st.radio("Période", ["Toutes les dates", "Actif à un instant", "Chevauche une plage"])
    instant = debut = fin = None
    if mode == "Actif à un instant":
        d = st.date_input("Date", value=datetime.now().date())
        h = st.time_input("Heure", value=datetime.now().time().replace(second=0, microsecond=0))
        instant = datetime.combine(d, h)
    elif mode == "Chevauche une plage":
        d1 = st.date_input("Du", value=datetime.now().date())
        d2 = st.date_input("Au", value=(datetime.now() + timedelta(days=2)).date())
        debut, fin = datetime.combine(d1, datetime.min.time()), datetime.combine(d2, datetime.max.time())

    recherche = st.text_input("Recherche", placeholder="RWY 16L, ILS, GPU…").strip().upper()

    st.header("Exclure")
    st.caption("Une règle par ligne. Les mots d'une même ligne sont combinés en ET : "
               "le NOTAM est masqué s'il les contient tous.")
    regles_txt = st.text_area("Règles de masquage", key="regles_txt", height=90,
                              placeholder=DEFAUT_REGLES)
    montrer_masques = st.checkbox("Afficher quand même les NOTAM masqués")

    st.header("Surligner")
    marques_txt = st.text_input("Mots en évidence (séparés par des virgules)", key="marques_txt")

regles = lire_regles(regles_txt)
termes = [t.strip() for t in marques_txt.split(",") if t.strip()]
maintenant = datetime.now()

affichees: list[tuple[Row, list[str] | None]] = []
masques = 0
for r in fus.rows:
    if r.icao not in icaos or r.categorie not in cats:
        continue
    if instant and not (r.debut <= instant <= r.fin):
        continue
    if fin and r.debut > fin:
        continue
    if debut and r.fin < debut:
        continue
    if recherche and recherche not in r.texte:
        continue
    regle = regle_qui_masque(r, regles)
    if regle:
        masques += 1
        if not montrer_masques:
            continue
    affichees.append((r, regle))

# --------------------------------------------------------------------------- #
# En-tête + document
# --------------------------------------------------------------------------- #

trajet = " / ".join(f"{b['dep']}→{b['dest']}" for b in st.session_state.bulletins)
st.markdown(f"### {len(st.session_state.bulletins)} vol(s) : {trajet}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("NOTAM affichés", len(affichees))
c2.metric("Total après fusion", len(fus.rows))
c3.metric("Doublons fusionnés", fus.doublons)
c4.metric("Masqués par règles", masques)

if not affichees:
    st.warning("Aucun NOTAM ne correspond aux filtres actuels.")
    st.stop()

TITRE = {"Départ": "TERRAIN DE DÉPART", "Destination": "TERRAIN DE DESTINATION",
         "Dégagement": "TERRAINS DE DÉGAGEMENT"}

section = aero = cat = None
for row, regle in affichees:
    principal = fus.role_principal[row.icao]
    sect = ("TERRAINS DE DÉGAGEMENT" if principal == "Dégagement"
            else "TERRAINS PRINCIPAUX — DÉPART / DESTINATION") if multi else TITRE[principal]
    if sect != section:
        section, aero, cat = sect, None, None
        st.markdown(f'<div class="nb-band">{sect}</div>', unsafe_allow_html=True)
    if row.icao != aero:
        aero, cat = row.icao, None
        roles = "   ·   ".join(f"{r} : {', '.join(fus.roles[row.icao][r])}"
                               for r in ORDRE_ROLE if r in fus.roles[row.icao])
        st.markdown(
            f'<div class="nb-aero"><h2><code>{row.icao}</code> <code>{row.iata}</code>'
            f'<span class="name">{row.nom}</span></h2>'
            + (f'<div class="nb-roles">{roles}</div>' if multi else "")
            + "</div>", unsafe_allow_html=True)
    if row.categorie != cat:
        cat = row.categorie
        fg, bg = PALETTE_CAT.get(cat, PALETTE_DEFAUT)
        st.markdown(f'<div class="nb-cat" style="color:{fg};background:{bg}">{cat}</div>',
                    unsafe_allow_html=True)

    st_key = row.statut(maintenant)
    sfg, sbg, slib = STATUT[st_key]
    vols = fus.sources.get(row.cle, [])
    tags = ""
    if multi and len(vols) > 1:
        tags += f'<span class="nb-tag">↻ {", ".join(vols)}</span>'
    if regle:
        tags += f'<span class="nb-tag" style="color:#8e1c1c;background:#fae9e5">⊘ {" + ".join(regle)}</span>'

    corps = []
    if row.n.daily:
        corps.append(f"DAILY {row.n.daily[0]}-{row.n.daily[1]}")
    corps += row.n.corps

    st.markdown(
        f'<div class="nb-notam" style="border-left-color:{sfg}">'
        f'<div class="nb-head"><span class="nb-id">{row.n.id}</span>'
        f'<span class="nb-pill" style="color:{sfg};background:{sbg}">{slib}</span>'
        f'<span class="nb-val">{row.debut_txt} → {row.fin_txt}'
        f'{" EST" if row.n.est else ""}</span>{tags}</div>'
        f'<p class="nb-body">{surligner(chr(10).join(corps), termes)}</p>'
        + (f'<div class="nb-meta">{chr(10).join(row.n.meta)}</div>' if row.n.meta else "")
        + "</div>", unsafe_allow_html=True)
