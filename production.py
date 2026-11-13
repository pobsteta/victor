"""Production de la vidéo tutoriel Néméton (specs/BRIEF-pilotage-video-victor-aigora.md).

VICTOR orchestre, il ne capture pas. Ce module ne contient que la logique sans
réseau ni audio : le journal de production, l'état du déroulé (lu dans le
journal, qui fait foi), le résumé des rushes pour le montage et les
vérifications d'avant assemblage. server.py fait le branchement (outil
production_video, tâches de fond, annonces vocales).

Journal (captures/journal.txt), une ligne par événement, toujours en ajout :

    <horodatage ISO local> | S<étape> | <action> | OK|ERREUR|ATTENTE | <détail>

S0 à S7 sont les étapes du déroulé du brief, pas les séquences du storyboard
(S1 à S8), qui servent dans resume-rushes.txt et dans rushes/ et voix/.
"""
import json
import os
import re
import time
from pathlib import Path

KIT = Path(os.path.expanduser(os.environ.get("VICTOR_KIT_VIDEO", "~/dev/nemeton-video")))

ETAPES = {
    0: "vérifications (projet de démo, application)",
    1: "séquences 1 et 2, visuels animés",
    2: "séquence 3, installation",
    3: "séquence 4, démo en trente secondes (radar)",
    4: "séquence 5, workflow en six fonctions",
    5: "séquence 7, l'application pilotée par MCP",
    6: "séquences 6 et 8, visuels animés",
    7: "assemblage",
}
STATUTS = ("OK", "ERREUR", "ATTENTE")
# Scènes de visuels-animes.html par étape du déroulé.
SCENES_ETAPE = {1: ["s1", "s2"], 6: ["s6", "s8"]}
SCENES_KIT = {"s1", "s2", "s5", "s6"}

# Repli si prompts-voix-off.md est absent : découpage du storyboard.
TIMECODES_DEFAUT = {1: ("0:00", "0:35"), 2: ("0:35", "1:30"), 3: ("1:30", "2:30"),
                    4: ("2:30", "3:45"), 5: ("3:45", "5:15"), 6: ("5:15", "6:15"),
                    7: ("6:15", "7:30"), 8: ("7:30", "8:00")}


def horodatage() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _champ(v, n: int = 200) -> str:
    """Un champ du journal : une seule ligne, sans le séparateur « | »."""
    return re.sub(r"\s+", " ", str(v if v is not None else "")).replace("|", "/").strip()[:n]


def captures(kit: Path = KIT) -> Path:
    return kit / "captures"


def journaliser(etape: int, action: str, statut: str, detail: str = "", kit: Path = KIT) -> str:
    """Ajoute une ligne au journal (jamais tronqué) et la renvoie."""
    etape = int(etape)
    if etape not in ETAPES:
        raise ValueError(f"étape inconnue : {etape} (0 à 7)")
    statut = statut.upper()
    if statut not in STATUTS:
        raise ValueError(f"statut inconnu : {statut} ({', '.join(STATUTS)})")
    ligne = " | ".join([horodatage(), f"S{etape}", _champ(action, 40) or "note", statut, _champ(detail)])
    dossier = captures(kit)
    dossier.mkdir(parents=True, exist_ok=True)
    with open(dossier / "journal.txt", "a", encoding="utf-8") as f:
        f.write(ligne + "\n")
    return ligne


def lire_journal(kit: Path = KIT) -> list[dict]:
    try:
        texte = (captures(kit) / "journal.txt").read_text(encoding="utf-8")
    except OSError:
        return []
    lignes = []
    for brut in texte.splitlines():
        champs = [c.strip() for c in brut.split(" | ")]
        if len(champs) < 4 or not re.fullmatch(r"S[0-7]", champs[1]):
            continue
        lignes.append({"t": champs[0], "etape": int(champs[1][1]), "action": champs[2],
                       "statut": champs[3], "detail": " | ".join(champs[4:])})
    return lignes


def _param(detail: str, nom: str) -> str | None:
    m = re.search(rf"(?:^|\s){nom}=(\S+)", detail or "")
    return m.group(1) if m else None


def etat_production(kit: Path = KIT) -> dict:
    """Où en est le déroulé, d'après le journal seul (il survit aux redémarrages).

    Une étape est faite quand le journal porte « etape_terminee | OK ». La
    production est arrêtée dès qu'une ERREUR suit la dernière « reprise » (ou
    le dernier « demarrer » réussi)."""
    lignes = lire_journal(kit)
    faites, arret, projet = set(), None, None
    for lg in lignes:
        if lg["action"] in ("reprise", "demarrer") and lg["statut"] == "OK":
            arret = None
        elif lg["statut"] == "ERREUR":
            arret = lg
        elif lg["action"] == "etape_terminee" and lg["statut"] == "OK":
            faites.add(lg["etape"])
        if lg["etape"] == 0 and lg["action"] == "demarrer" and lg["statut"] == "OK":
            projet = _param(lg["detail"], "projet") or projet
    restantes = [e for e in ETAPES if e not in faites]
    prochaine = restantes[0] if restantes else None
    return {
        "projet": projet,
        "etapes_faites": sorted(faites),
        "prochaine_etape": prochaine,
        "prochaine": ETAPES.get(prochaine, "production terminée"),
        "arretee": bool(arret),
        "erreur": f"S{arret['etape']} {arret['action']} : {arret['detail']}" if arret else None,
        "dernieres_lignes": [f"{x['t']} | S{x['etape']} | {x['action']} | {x['statut']} | {x['detail']}"
                             for x in lignes[-5:]],
    }


def fichiers_journalises(kit: Path = KIT) -> list[str]:
    """Fichiers produits, dans l'ordre du journal (champ fichier=…)."""
    vus = []
    for lg in lire_journal(kit):
        f = _param(lg["detail"], "fichier")
        if f and lg["statut"] == "OK" and f not in vus:
            vus.append(f)
    return vus


def _tc(v: str) -> str:
    """« 6:15 » -> « 00:06:15 » (format des horodatages du .srt)."""
    parts = [int(x) for x in v.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return f"{h:02d}:{m:02d}:{s:02d}"


def timecodes(kit: Path = KIT) -> dict[int, tuple[str, str]]:
    """Séquence du storyboard -> (début, fin), lus dans prompts-voix-off.md."""
    try:
        texte = (kit / "prompts-voix-off.md").read_text(encoding="utf-8")
    except OSError:
        texte = ""
    trouves = {int(n): (a, b) for n, a, b in
               re.findall(r"^## Séquence (\d+) \((\d+:\d\d) → (\d+:\d\d)\)", texte, re.M)}
    return {n: (_tc(a), _tc(b)) for n, (a, b) in (trouves or TIMECODES_DEFAUT).items()}


def _sequence_de(fichier: str) -> int | None:
    """Séquence du storyboard d'une capture : préfixe « 07-… », vidéo de l'app -> 7."""
    nom = Path(fichier).name
    m = re.match(r"(\d\d)-", nom)
    if m:
        return int(m.group(1))
    if nom.startswith("video-nemetonshiny"):
        return 7
    m = re.match(r"S(\d)\.", nom)
    return int(m.group(1)) if m else None


def rush_pret(sequence: int, kit: Path = KIT) -> Path | None:
    """rushes/S<n>.* : le rush retenu pour la séquence, celui que lit assemblage-ffmpeg.sh."""
    trouves = sorted((kit / "rushes").glob(f"S{sequence}.*"))
    return trouves[0] if trouves else None


def resume_rushes(kit: Path = KIT) -> tuple[Path, list[str]]:
    """Écrit captures/resume-rushes.txt : la liste de courses du montage.

    Une ligne par séquence du storyboard, dans l'ordre : timecode du .srt, rush
    retenu (rushes/S<n>.*) et captures candidates. assemblage-ffmpeg.sh lit
    l'ordre des séquences dans ce fichier (motif S<chiffre>) : l'en-tête n'en
    contient donc aucun. Renvoie le chemin et les séquences sans rush."""
    tcs = timecodes(kit)
    candidats: dict[int, list[str]] = {n: [] for n in tcs}
    connus = fichiers_journalises(kit) + sorted(p.name for p in captures(kit).glob("*")
                                                 if p.suffix in (".png", ".webm", ".mp4", ".pdf", ".gpkg"))
    for f in connus:
        n = _sequence_de(f)
        if n in candidats and f not in candidats[n]:
            candidats[n].append(f)
    lignes = [f"# Liste de courses du montage, écrite par VICTOR le {horodatage()}",
              "# séquence | début → fin (sous-titres.srt) | rush retenu | captures candidates"]
    manquants = []
    for n, (debut, fin) in sorted(tcs.items()):
        rush = rush_pret(n, kit)
        if not rush:
            manquants.append(f"S{n}")
        cands = ", ".join(c for c in candidats[n]) or "aucune"
        lignes.append(f"S{n} | {debut} → {fin} | rush={'rushes/' + rush.name if rush else 'MANQUANT'}"
                      f" | captures={cands}")
    chemin = captures(kit) / "resume-rushes.txt"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return chemin, manquants


def nombres_annonces(kit: Path = KIT) -> list[int]:
    """Nombres d'indicateurs dits dans la voix off et les sous-titres (« 41 indicateurs »,
    « 41 au total »)."""
    vus = set()
    for nom in ("prompts-voix-off.md", "sous-titres.srt"):
        try:
            texte = (kit / nom).read_text(encoding="utf-8")
        except OSError:
            continue
        texte = texte.split("## Version anglaise")[0]
        vus.update(int(x) for x in re.findall(r"\b(\d{2})\s+(?:sous-)?indicateurs\b", texte))
        vus.update(int(x) for x in re.findall(r"\b(\d{2})\s+au total\b", texte))
    return sorted(vus)


def nombre_reel(projet_id: str, racine: Path) -> int | None:
    """Indicateurs du calcul du projet (progress_state.json écrit par nemetonshiny)."""
    try:
        prog = json.loads((racine / projet_id / "data" / "progress_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    n = prog.get("indicators_total") if isinstance(prog, dict) else None
    return n if isinstance(n, int) and n > 0 else None


def verifier_indicateurs(projet_id: str | None, racine: Path, kit: Path = KIT) -> dict:
    """Garde-fou avant l'assemblage : le nombre dit en voix off (31 ou 41) doit
    être celui que calcule réellement le package."""
    annonces = nombres_annonces(kit)
    reel = nombre_reel(projet_id, racine) if projet_id else None
    coherent = reel is not None and annonces == [reel]
    if reel is None:
        avis = "nombre réel inconnu : aucun calcul lu pour le projet de démo"
    elif not annonces:
        avis = "aucun nombre d'indicateurs trouvé dans la voix off"
    elif coherent:
        avis = f"cohérent : {reel} indicateurs"
    else:
        avis = (f"incohérent : la voix off dit {' et '.join(map(str, annonces))}, "
                f"le calcul en compte {reel}")
    return {"annonces": annonces, "reel": reel, "coherent": coherent, "avis": avis}


def manquants_assemblage(kit: Path = KIT) -> dict:
    """Ce qui manque à assemblage-ffmpeg.sh, vérifié avant de le lancer (le script
    s'arrêterait au premier manque, après plusieurs minutes d'encodage)."""
    resume = captures(kit) / "resume-rushes.txt"
    if resume.exists():
        seqs = list(dict.fromkeys(re.findall(r"S[0-9]+", resume.read_text(encoding="utf-8"))))
    else:
        seqs = [f"S{n}" for n in range(1, 9)]
    voix = [s for s in seqs if not (kit / "voix" / f"{s}.mp3").exists()]
    rushes = [s for s in seqs if not rush_pret(int(s[1:]), kit)]
    return {"sequences": seqs, "voix": voix, "rushes": rushes,
            "srt": (kit / "sous-titres.srt").exists()}
