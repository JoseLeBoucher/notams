"""
Analyse de bulletins LIDO-NOTAM — module partagé par la version Streamlit.

Ne conserve que les 3 sections utiles (DEPARTURE / DESTINATION / DESTINATION
ALTERNATE(S)) et remonte tous les NOTAM, toutes catégories confondues.

Le repérage d'un NOTAM ne suppose aucun format d'identifiant : n'importe quelle
suite de caractères non-espace suivie d'un « / » et de chiffres convient. Le
verrou fiable est la présence littérale de « VALID: » juste après — c'est ce qui
évite de découper sur une simple mention d'ID dans le corps d'un autre NOTAM
(« REPLACES B3077/26 », « ANNOUNCED BY NOTAM B4963/26 »).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

# --------------------------------------------------------------------------- #
# Regex
# --------------------------------------------------------------------------- #

RE_SECTION = re.compile(r"^=+[ \t]*$\n^(?P<titre>[A-Z0-9()\- ]+?)[ \t]*$\n^=+[ \t]*$", re.M)
RE_AERO = re.compile(r"^(?P<icao>[A-Z]{4})[ \t]*/(?P<iata>[A-Z]{3})[ \t]+(?P<nom>.+?)[ \t]*$\n^-+[ \t]*$", re.M)
RE_CAT = re.compile(r"^\+{5,}[ \t]*(?P<cat>[A-Z ]+?)[ \t]*\+{5,}[ \t]*$", re.M)
RE_NOTAM = re.compile(
    r"^(?P<id>\S+/\d{2,4})[ \t]+VALID:[ \t]*"
    r"(?P<debut>\d{2}-[A-Z]{3}-\d{2}[ \t]\d{4})[ \t]*-[ \t]*"
    r"(?P<fin>PERM|UFN|\d{2}-[A-Z]{3}-\d{2}[ \t]\d{4})"
    r"(?P<est>[ \t]+EST)?[ \t]*$", re.M)
RE_CALL = re.compile(r"^(?P<cs>[A-Z]{2,3}\d+)/(?P<date>\d{1,2}[A-Z]{3})[ \t]+OFP-NR:[ \t]*(?P<ofp>\d+)", re.M)
RE_ROUTE = re.compile(r"^ROUTE:[ \t]+(?P<dep>\w{4})[ \t]*-[ \t]*(?P<dest>\w{4})[ \t]+ALTN:(?P<altn>[A-Z0-9 ]*)$", re.M)
RE_DAILY = re.compile(r"^[ \t]*DAILY[ \t]+(?P<de>\d{4})-(?P<a>\d{4})(?:[ \t]+EXC[ \t]+(?P<exc>\w+))?[ \t]*$", re.M)
RE_BULLETIN = re.compile(r"^NOTAM[ \t]*$\n^LIDO-NOTAM-BULLETIN", re.M)

SECTIONS_GARDEES = {"DEPARTURE AIRPORT", "DESTINATION AIRPORT", "DESTINATION ALTERNATE(S)"}
ROLE_PAR_SECTION = {"DEPARTURE AIRPORT": "Départ", "DESTINATION AIRPORT": "Destination",
                    "DESTINATION ALTERNATE(S)": "Dégagement"}
ORDRE_ROLE = ["Départ", "Destination", "Dégagement"]
SANS_CATEGORIE = "AUTRE"
FMT = "%d-%b-%y %H%M"
JAMAIS = datetime.max


# --------------------------------------------------------------------------- #
# Modèle
# --------------------------------------------------------------------------- #

@dataclass
class Notam:
    id: str
    debut: datetime | None
    debut_txt: str
    fin: datetime | None          # None = PERM / UFN
    fin_txt: str
    est: bool
    corps: list[str] = field(default_factory=list)
    meta: list[str] = field(default_factory=list)
    daily: tuple[str, str] | None = None
    brut: str = ""


@dataclass
class Row:
    section: str
    icao: str
    iata: str
    nom: str
    categorie: str
    n: Notam
    source: str = ""

    @property
    def role(self) -> str:
        return ROLE_PAR_SECTION.get(self.section, self.section)

    @property
    def cle(self) -> tuple[str, str]:
        return (self.icao, self.n.id)

    @property
    def debut(self) -> datetime:
        return self.n.debut or datetime.min

    @property
    def fin(self) -> datetime:
        return self.n.fin or JAMAIS

    @property
    def debut_txt(self) -> str:
        return self.n.debut_txt.upper()

    @property
    def fin_txt(self) -> str:
        return self.n.fin_txt.upper()

    @property
    def texte(self) -> str:
        return f"{self.n.id}\n{self.n.brut}".upper()

    def statut(self, maintenant: datetime) -> str:
        if self.debut > maintenant:
            return "futur"
        return "actif" if self.fin >= maintenant else "expire"


@dataclass
class Bulletin:
    callsign: str
    dep: str
    dest: str
    altn: list[str]
    rows: list[Row]


# --------------------------------------------------------------------------- #
# Analyse
# --------------------------------------------------------------------------- #

def _date(s: str) -> datetime | None:
    try:
        return datetime.strptime(re.sub(r"[ \t]+", " ", s.strip()), FMT)
    except ValueError:
        return None


def _decouper(motif: re.Pattern, texte: str) -> list[tuple[re.Match, str]]:
    ms = list(motif.finditer(texte))
    return [(m, texte[m.end():ms[i + 1].start() if i + 1 < len(ms) else len(texte)])
            for i, m in enumerate(ms)]


def _notams(texte: str) -> list[Notam]:
    ms = list(RE_NOTAM.finditer(texte))
    out = []
    for i, m in enumerate(ms):
        brut = texte[m.end():ms[i + 1].start() if i + 1 < len(ms) else len(texte)].strip()
        daily = RE_DAILY.search(brut)
        corps, meta = [], []
        for ligne in brut.splitlines():
            t = ligne.strip()
            if not t or (daily and t.startswith("DAILY")):
                continue
            (meta if t.startswith("REF ") else corps).append(t)
        fin_txt = m.group("fin")
        out.append(Notam(
            id=m.group("id"),
            debut=_date(m.group("debut")), debut_txt=re.sub(r"[ \t]+", " ", m.group("debut")),
            fin=None if fin_txt in ("PERM", "UFN") else _date(fin_txt),
            fin_txt=re.sub(r"[ \t]+", " ", fin_txt),
            est=bool(m.group("est")),
            corps=corps, meta=meta,
            daily=(daily.group("de"), daily.group("a")) if daily else None,
            brut=brut,
        ))
    return out


def parse_bulletin(texte: str) -> Bulletin:
    call, route = RE_CALL.search(texte), RE_ROUTE.search(texte)
    rows: list[Row] = []

    for sm, sec_txt in _decouper(RE_SECTION, texte):
        titre = sm.group("titre").strip()
        if titre not in SECTIONS_GARDEES:
            continue
        for am, aero_txt in _decouper(RE_AERO, sec_txt):
            nom = re.sub(r" - DETAILED INFO|/DEST ALTN|/DEP ALTN", "", am.group("nom")).strip()
            corps = aero_txt.strip()
            if not corps or corps == "NIL":
                continue
            paquets = _decouper(RE_CAT, corps)
            blocs = ([(cm.group("cat").strip(), txt) for cm, txt in paquets]
                     if paquets else [(SANS_CATEGORIE, corps)])
            for cat, txt in blocs:
                for n in _notams(txt):
                    rows.append(Row(section=titre, icao=am.group("icao"), iata=am.group("iata"),
                                    nom=nom, categorie=cat or SANS_CATEGORIE, n=n))

    return Bulletin(
        callsign=call.group("cs") if call else "",
        dep=route.group("dep") if route else "",
        dest=route.group("dest") if route else "",
        altn=route.group("altn").split() if route else [],
        rows=rows,
    )


def decouper_bulletins(texte: str) -> list[str]:
    """Un collage peut contenir plusieurs bulletins bout à bout."""
    pos = [m.start() for m in RE_BULLETIN.finditer(texte)]
    if len(pos) < 2:
        return [texte]
    return [texte[p:pos[i + 1] if i + 1 < len(pos) else len(texte)] for i, p in enumerate(pos)]
