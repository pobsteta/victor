"""Journal des dictées (brief nemetonshiny 2026-11-10-journal-des-dictees).

Recueille ce que la transcription livre réellement (champ `dit`) à côté de ce
que VICTOR en fait (outils, délégations, résultats), pour régler sur de vraies
dictées la résolution des noms de projets de nemetonshiny (fixture
noms_dictes.csv, seuil de distance).

- Désactivé par défaut : VICTOR_JOURNAL_DICTEES=<chemin d'un fichier .jsonl>.
- Local, en ajout seul, une ligne JSON par événement ; rotation à
  VICTOR_JOURNAL_DICTEES_MAX_MO (défaut 5) : le fichier plein devient <chemin>.1
  (un seul ancien gardé).
- Jamais de jeton de confirmation ni de bloc NEMETON_CONFIRMATION ; pas d'audio.
- N'interrompt jamais un tour : une erreur d'écriture est avalée et signalée
  une seule fois en stderr.
"""
import json
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import confirmation as conf

PARIS = ZoneInfo("Europe/Paris")
# Outils qui touchent à un nom de projet : les seuls journalisés.
OUTILS = {"nemeton_fiche", "nemeton_etat", "open_nemeton", "delegate_to_claude", "confirmer_ecriture"}
SECRETS = {"jeton", "token", "api_key", "apikey", "password", "mot_de_passe", "secret"}


def _chemin() -> Path | None:
    v = os.environ.get("VICTOR_JOURNAL_DICTEES", "").strip()
    return Path(os.path.expanduser(v)) if v else None


def _max_octets() -> int:
    try:
        return max(1, int(float(os.environ.get("VICTOR_JOURNAL_DICTEES_MAX_MO", "5")) * 1024 * 1024))
    except ValueError:
        return 5 * 1024 * 1024


_verrou = threading.Lock()
_erreur_signalee = False


def actif() -> bool:
    return _chemin() is not None


def masquer(v):
    """Copie sans secret : clés sensibles retirées, blocs de confirmation coupés."""
    if isinstance(v, dict):
        return {k: masquer(x) for k, x in v.items() if str(k).lower() not in SECRETS}
    if isinstance(v, list):
        return [masquer(x) for x in v]
    if isinstance(v, str) and conf.contient_confirmation(v):
        return conf.extraire(v)[0] + " [bloc de confirmation retiré]"
    return v


def ecrire(evt: dict, chemin: Path | None = None) -> bool:
    """Ajoute un événement. Ne lève jamais : renvoie False si rien n'est écrit."""
    global _erreur_signalee
    chemin = chemin or _chemin()
    if not chemin:
        return False
    ligne = {"t": datetime.now(PARIS).isoformat(timespec="seconds"), **masquer(evt)}
    try:
        texte = json.dumps(ligne, ensure_ascii=False, default=str) + "\n"
        with _verrou:
            chemin.parent.mkdir(parents=True, exist_ok=True)
            try:
                if chemin.stat().st_size + len(texte.encode()) > _max_octets():
                    os.replace(chemin, chemin.with_name(chemin.name + ".1"))
            except FileNotFoundError:
                pass
            fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(texte)
        return True
    except Exception as exc:  # noqa: BLE001 — le journal ne doit jamais faire tomber un tour
        if not _erreur_signalee:
            _erreur_signalee = True
            print(f"[journal des dictées] écriture impossible ({chemin}) : {exc}", file=sys.stderr, flush=True)
        return False


def resultat_outil(res) -> dict:
    """Résumé d'un résultat d'outil VICTOR : succès, ou code et candidats."""
    if not isinstance(res, dict):
        return {"ok": None}
    out = {"ok": res.get("ok", res.get("status") not in (None, "error"))}
    for k in ("code", "erreur", "error", "candidats", "deleguer", "abandonne", "projet", "nom",
              "task_id", "status"):
        if k in res:
            out[k] = res[k]
    return masquer(out)


def resultat_tache(statut: str, sortie: str) -> dict:
    """Résultat d'une tâche déléguée : statut, et le dernier objet JSON qui porte
    un `code` d'erreur MCP (projet_introuvable, projet_ambigu…) avec ses
    candidats. La sortie de claude -p est du texte libre : on n'y cherche que ça."""
    out = {"statut": statut}
    texte = conf.extraire(sortie or "")[0]
    dec = json.JSONDecoder()
    trouve = None
    for m in re.finditer(r'\{\s*"', texte):
        try:
            obj, _ = dec.raw_decode(texte, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("code"), str):
            trouve = obj
    if trouve:
        out["code"] = trouve["code"]
        if isinstance(trouve.get("candidats"), list):
            out["candidats"] = trouve["candidats"]
    else:
        noms = re.findall(r"\b(projet_introuvable|projet_ambigu|confirmation_requise|jeton_invalide)\b", texte)
        if noms:
            out["code"] = noms[-1]
    out["extrait"] = texte[-300:]
    return masquer(out)
