"""Environnement des tests : posé AVANT tout import de server.py.

server.py lit ses réglages à l'import (clés, dossiers, journal). On les pointe
vers des valeurs factices et un dossier jetable : aucun réseau, aucune clé
réelle, aucun fichier de l'utilisateur touché.
"""
import os
import tempfile
from pathlib import Path

_BAC = Path(tempfile.mkdtemp(prefix="victor-tests-"))
for _d in ("travail", "projets", "kit"):
    (_BAC / _d).mkdir()

# Valeurs posées de force : un .env ou un shell de développeur ne doit pas les changer.
os.environ.update({
    "GRADIUM_API_KEY": "cle-factice",
    "ANTHROPIC_API_KEY": "cle-factice",
    "VICTOR_WORKDIR": str(_BAC / "travail"),
    "NEMETON_PROJETS": str(_BAC / "projets"),
    "VICTOR_KIT_VIDEO": str(_BAC / "kit"),
    "NEMETON_MCP_VUES_DIR": str(_BAC / "vues"),
})
for _k in ("VICTOR_JOURNAL_DICTEES", "VICTOR_JOURNAL_DICTEES_MAX_MO", "VICTOR_ESPACES",
           "VICTOR_ESPACES_DESC", "VICTOR_VOICE_ID", "VICTOR_TITRE", "VICTOR_GENRE"):
    os.environ.pop(_k, None)
