"""Tests de caractérisation de journal_dictees.py."""
import json

import pytest

import confirmation as conf
import journal_dictees as jd

JETON_BLOC = conf.prompt_tache2(json.dumps({
    "outil": "appliquer_ugf", "projet": "p", "projet_nom": "P", "jeton": "SECRET42",
    "expire_a": "2026-11-11T09:30:00Z", "arguments": {}}))


@pytest.fixture(autouse=True)
def _env_propre(monkeypatch):
    monkeypatch.delenv("VICTOR_JOURNAL_DICTEES", raising=False)
    monkeypatch.delenv("VICTOR_JOURNAL_DICTEES_MAX_MO", raising=False)
    monkeypatch.setattr(jd, "_erreur_signalee", False)


# ------------------------------------------------------------------ masquer

def test_masquer_retire_les_cles_secretes_a_tout_niveau():
    v = {"a": 1, "Jeton": "x", "imbrique": {"API_KEY": "y", "ok": 2}, "liste": [{"password": "z", "n": 3}]}
    assert jd.masquer(v) == {"a": 1, "imbrique": {"ok": 2}, "liste": [{"n": 3}]}


def test_masquer_laisse_passer_le_reste():
    assert jd.masquer("texte") == "texte"
    assert jd.masquer(5) == 5
    assert jd.masquer(None) is None


def test_masquer_coupe_le_bloc_de_confirmation_dans_une_chaine():
    sortie = jd.masquer(f"Avant\n{JETON_BLOC}")
    assert "SECRET42" not in sortie
    # Seul le bloc balisé est retiré ; la phrase de confirmation qui le précède reste (sans secret).
    assert sortie == "Avant\nL'utilisateur a confirmé oralement. [bloc de confirmation retiré]"


def test_masquer_phrase_seule_est_aussi_marquee():
    assert jd.masquer(conf.PHRASE).endswith("[bloc de confirmation retiré]")


# ------------------------------------------------------------------ actif / chemin

def test_actif_desactive_par_defaut():
    assert jd.actif() is False


def test_actif_avec_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("VICTOR_JOURNAL_DICTEES", str(tmp_path / "j.jsonl"))
    assert jd.actif() is True


def test_ecrire_sans_chemin_ne_fait_rien():
    assert jd.ecrire({"a": 1}) is False


# ------------------------------------------------------------------ ecrire

def test_ecrire_ajoute_une_ligne_json_horodatee(tmp_path):
    f = tmp_path / "sous" / "j.jsonl"
    assert jd.ecrire({"evt": "dit", "dit": "bonjour é"}, f) is True
    assert jd.ecrire({"evt": "outil"}, f) is True
    lignes = f.read_text(encoding="utf-8").splitlines()
    assert len(lignes) == 2
    premiere = json.loads(lignes[0])
    assert premiere["dit"] == "bonjour é" and premiere["evt"] == "dit"
    assert premiere["t"].startswith("20") and "T" in premiere["t"]  # horodatage ISO local, à la seconde


def test_ecrire_utilise_la_variable_d_environnement(monkeypatch, tmp_path):
    f = tmp_path / "env.jsonl"
    monkeypatch.setenv("VICTOR_JOURNAL_DICTEES", str(f))
    assert jd.ecrire({"x": 1}) is True
    assert json.loads(f.read_text())["x"] == 1


def test_ecrire_masque_les_secrets(tmp_path):
    f = tmp_path / "j.jsonl"
    jd.ecrire({"jeton": "SECRET42", "sortie": JETON_BLOC}, f)
    contenu = f.read_text(encoding="utf-8")
    assert "SECRET42" not in contenu
    assert "NEMETON_CONFIRMATION" not in contenu


def test_ecrire_permissions_privees(tmp_path):
    f = tmp_path / "j.jsonl"
    jd.ecrire({"x": 1}, f)
    assert (f.stat().st_mode & 0o777) == 0o600


def test_ecrire_rotation_au_depassement(monkeypatch, tmp_path):
    f = tmp_path / "j.jsonl"
    monkeypatch.setattr(jd, "_max_octets", lambda: 300)
    for i in range(6):
        assert jd.ecrire({"i": i, "bourrage": "x" * 60}, f) is True
    ancien = f.with_name("j.jsonl.1")
    assert ancien.exists()
    assert f.stat().st_size <= 300
    ids = [json.loads(l)["i"] for l in ancien.read_text().splitlines() + f.read_text().splitlines()]
    # Un seul ancien fichier est gardé : les plus vieux événements peuvent avoir disparu,
    # mais le dernier est toujours dans le fichier courant, dans l'ordre.
    assert ids == sorted(ids) and ids[-1] == 5


def test_ecrire_ne_leve_jamais_et_signale_une_seule_fois(tmp_path, capsys):
    bloquant = tmp_path / "fichier"
    bloquant.write_text("je suis un fichier")
    chemin = bloquant / "j.jsonl"  # le « dossier » parent est un fichier
    assert jd.ecrire({"a": 1}, chemin) is False
    assert jd.ecrire({"a": 2}, chemin) is False
    err = capsys.readouterr().err
    assert err.count("[journal des dictées] écriture impossible") == 1


@pytest.mark.parametrize("valeur, attendu", [
    ("5", 5 * 1024 * 1024),
    ("0.5", 512 * 1024),
    ("abc", 5 * 1024 * 1024),
    ("0", 1),
    ("-3", 1),
])
def test_max_octets(monkeypatch, valeur, attendu):
    monkeypatch.setenv("VICTOR_JOURNAL_DICTEES_MAX_MO", valeur)
    assert jd._max_octets() == attendu


def test_max_octets_defaut():
    assert jd._max_octets() == 5 * 1024 * 1024


# ------------------------------------------------------------------ resultat_outil

def test_resultat_outil_non_dict():
    assert jd.resultat_outil("texte") == {"ok": None}
    assert jd.resultat_outil(None) == {"ok": None}


def test_resultat_outil_ok_explicite():
    assert jd.resultat_outil({"ok": False, "code": "projet_ambigu", "candidats": ["a", "b"], "inutile": 1}) == {
        "ok": False, "code": "projet_ambigu", "candidats": ["a", "b"]}


def test_resultat_outil_ok_deduit_du_statut():
    assert jd.resultat_outil({"status": "running", "task_id": "t1"}) == {
        "ok": True, "task_id": "t1", "status": "running"}
    assert jd.resultat_outil({"status": "error", "error": "boum"})["ok"] is False
    assert jd.resultat_outil({})["ok"] is False  # status absent -> None not in (None, "error") est faux


def test_resultat_outil_masque_les_secrets():
    r = jd.resultat_outil({"ok": True, "erreur": JETON_BLOC})
    assert "SECRET42" not in json.dumps(r)


# ------------------------------------------------------------------ resultat_tache

def test_resultat_tache_json_avec_code_et_candidats():
    sortie = 'blabla {"code": "projet_ambigu", "candidats": ["A (1)", "B (2)"]} fin'
    r = jd.resultat_tache("termine", sortie)
    assert r["statut"] == "termine"
    assert r["code"] == "projet_ambigu"
    assert r["candidats"] == ["A (1)", "B (2)"]
    assert r["extrait"].endswith("fin")


def test_resultat_tache_garde_le_dernier_objet_a_code():
    sortie = '{"code": "projet_introuvable"} puis {"code": "projet_ambigu"}'
    assert jd.resultat_tache("termine", sortie)["code"] == "projet_ambigu"


def test_resultat_tache_repli_sur_les_noms_de_code_dans_le_texte():
    r = jd.resultat_tache("echec", "erreur : jeton_invalide puis projet_introuvable")
    assert r["code"] == "projet_introuvable"
    assert "candidats" not in r


def test_resultat_tache_sans_code():
    r = jd.resultat_tache("termine", "tout va bien")
    assert r == {"statut": "termine", "extrait": "tout va bien"}


def test_resultat_tache_sortie_vide_ou_none():
    assert jd.resultat_tache("annule", "") == {"statut": "annule", "extrait": ""}
    assert jd.resultat_tache("annule", None) == {"statut": "annule", "extrait": ""}


def test_resultat_tache_extrait_limite_a_300_caracteres():
    r = jd.resultat_tache("termine", "a" * 1000 + "FIN")
    assert len(r["extrait"]) == 300 and r["extrait"].endswith("FIN")


def test_resultat_tache_retire_le_bloc_de_confirmation():
    r = jd.resultat_tache("termine", f"fait.\n{JETON_BLOC}")
    assert "SECRET42" not in json.dumps(r)
    assert "NEMETON_CONFIRMATION" not in json.dumps(r)
