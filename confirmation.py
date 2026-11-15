"""Confirmation à la voix des écritures Néméton (brief nemetonshiny
2026-11-10-relais-vocal-confirmation, ADR 0002 de nemetonshiny).

Une écriture (appliquer_ugf, croiser_onf…) se fait en deux tâches Claude Code :

1. la tâche 1 reçoit `confirmation_requise` du serveur MCP et termine sa sortie
   par un bloc balisé qui porte le jeton :

       <<<NEMETON_CONFIRMATION
       {"outil": …, "projet": …, "projet_nom": …, "jeton": …, "expire_a": …, "arguments": {…}}
       NEMETON_CONFIRMATION>>>

2. après un « oui » explicite de l'utilisateur, VICTOR lance la tâche 2 avec le
   gabarit exact de `prompt_tache2()`.

Le jeton ne sort de VICTOR que dans le prompt de la tâche 2 : le bloc est retiré
de la sortie de la tâche 1 avant que la page ou le modèle vocal la voient, et
gardé côté serveur ; le prompt affiché de la tâche 2 est masqué.
"""
import json
import re
import threading
import time
from datetime import datetime, timezone

DEBUT = "<<<NEMETON_CONFIRMATION"
FIN = "NEMETON_CONFIRMATION>>>"
PHRASE = "L'utilisateur a confirmé oralement."
CLES = ("outil", "projet", "projet_nom", "jeton", "expire_a", "arguments")
_BLOC = re.compile(re.escape(DEBUT) + r"\s*\n(.*?)\n\s*" + re.escape(FIN), re.S)


def _expire_ts(v) -> float | None:
    """« 2026-11-11T09:30:00Z » -> horodatage POSIX, None si illisible."""
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        d = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def valider(obj) -> dict | None:
    """Le bloc s'il porte les six clés, bien typées ; sinon None."""
    if not isinstance(obj, dict) or any(k not in obj for k in CLES):
        return None
    if not all(isinstance(obj[k], str) and obj[k].strip() for k in CLES if k != "arguments"):
        return None
    if not isinstance(obj["arguments"], dict) or "jeton" in obj["arguments"]:
        return None
    if not re.fullmatch(r"[A-Za-z_][\w]*", obj["outil"]) or _expire_ts(obj["expire_a"]) is None:
        return None
    return obj


def extraire(texte: str) -> tuple[str, dict | None, str | None]:
    """Retire de la sortie d'une tâche TOUS les blocs de confirmation.

    Renvoie (texte sans bloc, bloc retenu, bloc brut retenu). Le bloc retenu est
    le dernier bloc valide ; le brut est sa ligne JSON telle quelle, recopiée
    sans retouche dans la tâche 2. Un bloc invalide est retiré aussi (il peut
    porter un jeton) mais n'est pas retenu."""
    texte = texte or ""
    retenu, brut = None, None
    for m in _BLOC.finditer(texte):
        ligne = m.group(1).strip()
        try:
            obj = json.loads(ligne)
        except ValueError:
            continue
        if valider(obj):
            retenu, brut = obj, ligne
    # Balise ouvrante sans fermeture (sortie tronquée) : on coupe tout ce qui suit.
    propre = _BLOC.sub("", texte)
    if DEBUT in propre:
        propre = propre[:propre.index(DEBUT)]
    return propre.strip(), retenu, brut


def expire(bloc: dict, maintenant: float | None = None) -> bool:
    ts = _expire_ts(bloc.get("expire_a"))
    return ts is None or (maintenant if maintenant is not None else time.time()) >= ts


def prompt_tache2(brut: str) -> str:
    """Gabarit unique de la tâche 2, identique chez VICTOR et dans l'espace aigora."""
    return f"{PHRASE}\n{DEBUT}\n{brut}\n{FIN}"


def prompt_affiche(bloc: dict) -> str:
    """Ce que la page voit du prompt de la tâche 2 : jamais le jeton."""
    return f"[confirmation de {bloc['outil']} sur {bloc['projet_nom']}]"


def contient_confirmation(texte: str) -> bool:
    """Un prompt délégué ne doit jamais porter la confirmation : seule la
    tâche 2 lancée par VICTOR le peut."""
    return DEBUT in (texte or "") or FIN in (texte or "") or PHRASE in (texte or "")


def resume_pour_voix(bloc: dict) -> dict:
    """Ce que le modèle vocal reçoit du bloc : sans jeton ni arguments."""
    return {"outil": bloc["outil"], "projet": bloc["projet"], "projet_nom": bloc["projet_nom"],
            "expire_a": bloc["expire_a"]}


class Attentes:
    """Blocs en attente du « oui », par task_id de la tâche 1 (côté serveur)."""

    def __init__(self):
        self._blocs: dict[str, tuple[dict, str]] = {}
        self._verrou = threading.Lock()

    def garder(self, task_id: str, bloc: dict, brut: str):
        with self._verrou:
            self._blocs[task_id] = (bloc, brut)

    def prendre(self, task_id: str) -> tuple[dict, str] | None:
        """Retire et rend le bloc (usage unique, utilisé ou non)."""
        with self._verrou:
            return self._blocs.pop(task_id, None)

    def jeter_expires(self, maintenant: float | None = None) -> list[str]:
        with self._verrou:
            morts = [t for t, (b, _) in self._blocs.items() if expire(b, maintenant)]
            for t in morts:
                del self._blocs[t]
        return morts

    def en_attente(self) -> list[str]:
        with self._verrou:
            return list(self._blocs)
