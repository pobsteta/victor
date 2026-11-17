"""Fonctions pures de server.py.

Import possible sans modifier server.py : tests/conftest.py pose l'environnement
(clés factices, dossiers jetables) avant. L'import ne lance ni serveur, ni
réseau, ni processus. Aucun test ne démarre l'application.
"""
import json
import os
import time

import pytest

import server as s


# ------------------------------------------------------------------ parse_espaces

def test_import_n_utilise_que_l_environnement_de_test():
    assert s.GRADIUM_API_KEY == "cle-factice"
    assert s.ESPACE_DEFAUT == "defaut"
    assert s.NOM == "VICTOR"


def test_parse_espaces_vide_donne_un_espace_defaut(tmp_path):
    espaces, defaut = s.parse_espaces("", "", str(tmp_path))
    assert defaut == "defaut"
    assert espaces == {"defaut": {"path": str(tmp_path), "desc": "dossier de travail par défaut"}}


def test_parse_espaces_nomme_et_decrit(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    espaces, defaut = s.parse_espaces(f"Nemeton:{a};autre:{b}", "nemeton:Les forêts", str(a))
    assert espaces == {"nemeton": {"path": str(a), "desc": "Les forêts"},
                       "autre": {"path": str(b), "desc": ""}}
    assert defaut == "nemeton"  # le workdir correspond à cet espace


def test_parse_espaces_workdir_hors_liste_devient_defaut(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    espaces, defaut = s.parse_espaces(f"a:{a}", "", str(tmp_path))
    assert defaut == "defaut"
    assert set(espaces) == {"a", "defaut"}
    assert espaces["defaut"]["path"] == str(tmp_path)


def test_parse_espaces_ignore_un_dossier_inexistant(tmp_path, capsys):
    espaces, _ = s.parse_espaces(f"fantome:{tmp_path / 'nope'}", "", str(tmp_path))
    assert "fantome" not in espaces
    assert "espace « fantome » ignoré" in capsys.readouterr().out


def test_paires_ne_coupe_qu_au_premier_deux_points():
    assert s._paires("C:C:/dossier; Autre : x ;vide:;:sans_nom;sanssep") == [
        ("c", "C:/dossier"), ("autre", "x")]


# ------------------------------------------------------------------ _norm

@pytest.mark.parametrize("entree, attendu", [
    ("Forêt d'Écouves", "foret d ecouves"),
    ("  Couchey—Nord!! ", "couchey nord"),
    ("", ""),
    (None, ""),
    ("ÀÉÎÕÜ", "aeiou"),
])
def test_norm(entree, attendu):
    assert s._norm(entree) == attendu


# ------------------------------------------------------------------ id_a_dire

def test_id_a_dire_annee_courante():
    assert s.id_a_dire("20261008_212542_uywc", 2026) == "créé le 8 octobre, identifiant se terminant par u y w c"


def test_id_a_dire_autre_annee():
    assert s.id_a_dire("20250315_010101_ab12", 2026) == "créé le 15 mars 2025, identifiant se terminant par a b 1 2"


def test_id_a_dire_premier_du_mois():
    assert s.id_a_dire("20261101_000000_zzzz", 2026).startswith("créé le premier novembre,")


def test_id_a_dire_annee_par_defaut_est_l_annee_locale():
    annee = time.localtime().tm_year
    assert " " + str(annee) not in s.id_a_dire(f"{annee}0220_101010_abcd")


@pytest.mark.parametrize("pid", ["", None, "n'importe quoi", "20261308_212542_uywc",
                                 "20260008_212542_uywc", "20261008_212542_UYWC", "20261008_212542_abc"])
def test_id_a_dire_refuse_les_formes_inattendues(pid):
    assert s.id_a_dire(pid, 2026) is None


# ------------------------------------------------------------------ extraire_vue

URL = "https://claude.ai/artifact/abc-123"


def test_extraire_vue_trouve_le_bloc():
    texte = 'Voilà : {"vue": {"type": "atlas", "projet": "p1", "url": "%s"}} fin' % URL
    assert s.extraire_vue(texte) == {"type": "atlas", "projet": "p1", "url": URL}


def test_extraire_vue_garde_la_derniere_valide():
    a = json.dumps({"vue": {"type": "atlas", "url": URL + "1"}})
    b = json.dumps({"vue": {"type": "calcul", "url": URL + "2"}})
    assert s.extraire_vue(f"{a}\n{b}")["url"] == URL + "2"


def test_extraire_vue_type_et_projet_absents_deviennent_vides():
    assert s.extraire_vue(json.dumps({"vue": {"url": URL}})) == {"type": "", "projet": "", "url": URL}


@pytest.mark.parametrize("url", ["http://claude.ai/artifact/x", "https://evil.example/artifact/x",
                                 "https://claude.ai/autre/x", "javascript:alert(1)", 5])
def test_extraire_vue_refuse_les_urls_hors_artefacts_claude(url):
    assert s.extraire_vue(json.dumps({"vue": {"type": "atlas", "url": url}})) is None


@pytest.mark.parametrize("texte", ["", None, "pas de vue", '{"vue": ', '{"vue": "chaine"}', '{"vue": {}}'])
def test_extraire_vue_rien(texte):
    assert s.extraire_vue(texte) is None


# ------------------------------------------------------------------ _statut_job

def test_statut_job_termine_est_inchange():
    assert s._statut_job({"statut": "termine"}) == ("termine", None)


def test_statut_job_vide_est_aucun():
    assert s._statut_job({}) == ("aucun", None)


def test_statut_job_en_cours_avec_processus_vivant():
    assert s._statut_job({"statut": "en_cours", "pid": os.getpid()}) == ("en_cours", None)


def test_statut_job_en_cours_processus_mort_devient_echec():
    statut, erreur = s._statut_job({"statut": "en_cours", "pid": 2 ** 22 + 12345})
    assert statut == "echec"
    assert erreur == "le processus de calcul s'est arrêté sans terminer"


def test_statut_job_sans_pid_recent_reste_en_lancement():
    maintenant = time.strftime("%Y-%m-%dT%H:%M:%S")
    assert s._statut_job({"statut": "lancement", "lance_a": maintenant})[0] == "lancement"


def test_statut_job_sans_pid_ancien_ou_sans_date_devient_echec():
    ancien = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 3600))
    assert s._statut_job({"statut": "lancement", "lance_a": ancien})[0] == "echec"
    assert s._statut_job({"statut": "en_cours"})[0] == "echec"


def test_statut_job_echec_garde_son_erreur():
    assert s._statut_job({"statut": "echec", "erreur": "boum"}) == ("echec", "boum")


def test_pid_vivant():
    assert s._pid_vivant(os.getpid()) is True
    assert s._pid_vivant("abc") is False
    assert s._pid_vivant(0) is False
    assert s._pid_vivant(-5) is False
    assert s._pid_vivant(None) is False


# ------------------------------------------------------------------ calculs_a_annoncer

def etat(statut, job_id="j1"):
    return {"job_id": job_id, "statut": statut}


def test_calculs_a_annoncer_transition_vers_une_fin():
    assert s.calculs_a_annoncer({"p": etat("en_cours")}, {"p": etat("termine")}) == ["p"]


def test_calculs_a_annoncer_nouveau_projet_deja_fini():
    assert s.calculs_a_annoncer({}, {"p": etat("echec")}) == ["p"]


def test_calculs_a_annoncer_pas_deux_fois():
    assert s.calculs_a_annoncer({"p": etat("termine")}, {"p": etat("termine")}) == []


def test_calculs_a_annoncer_nouveau_job_apres_un_ancien_termine():
    assert s.calculs_a_annoncer({"p": etat("termine", "j1")}, {"p": etat("termine", "j2")}) == ["p"]


def test_calculs_a_annoncer_pas_de_fin_encore():
    assert s.calculs_a_annoncer({"p": etat("lancement")}, {"p": etat("en_cours")}) == []


def test_calculs_a_annoncer_annule_compte():
    assert s.calculs_a_annoncer({"p": etat("en_cours")}, {"p": etat("annule")}) == ["p"]


# ------------------------------------------------------------------ message_calcul

def projet_factice(racine, pid, nom):
    d = racine / pid
    (d / "data").mkdir(parents=True)
    (d / "metadata.json").write_text(json.dumps({"name": nom}), encoding="utf-8")
    return d


def test_message_calcul_echec_utilise_le_nom_et_l_erreur(tmp_path):
    projet_factice(tmp_path, "p1", "Couchey")
    m = s.message_calcul("p1", {"statut": "echec", "erreur": "R a planté"}, tmp_path)
    assert m.startswith("[SYSTÈME] Calcul Néméton : le calcul du projet « Couchey » (p1) a échoué (R a planté).")


def test_message_calcul_echec_sans_erreur(tmp_path):
    m = s.message_calcul("inconnu", {"statut": "echec"}, tmp_path)
    assert "« inconnu » (inconnu)" in m and "erreur inconnue" in m


def test_message_calcul_annule(tmp_path):
    projet_factice(tmp_path, "p1", "Couchey")
    assert s.message_calcul("p1", {"statut": "annule"}, tmp_path).endswith("est annulé. Dis-le en une phrase.")


def test_message_calcul_rapport_pret(tmp_path):
    projet_factice(tmp_path, "p1", "Couchey")
    m = s.message_calcul("p1", {"statut": "termine", "type": "rapport"}, tmp_path)
    assert "le rapport PDF du projet « Couchey »" in m and "est prêt" in m


def test_message_calcul_onf_avec_resultat(tmp_path):
    projet_factice(tmp_path, "p1", "Couchey")
    res = {"n_ugf": [4], "n_parcelles": 12, "ecartees": ["a", "b"], "indicateurs_perimes": [True]}
    m = s.message_calcul("p1", {"statut": "termine", "type": "onf", "resultat": res}, tmp_path)
    assert "4 unités de gestion, 12 parcelles, 2 parcelles écartées du projet" in m
    assert "périmés" in m


def test_message_calcul_termine_sans_vue_propose_d_ouvrir_l_application(tmp_path):
    projet_factice(tmp_path, "p1", "Couchey")
    m = s.message_calcul("p1", {"statut": "termine"}, tmp_path)
    assert "est terminé" in m
    assert m.endswith("Propose d'ouvrir l'application Néméton pour voir les résultats.")


def test_message_calcul_nom_nettoye(tmp_path):
    projet_factice(tmp_path, "p1", "Co<u>chey*")
    assert "« Couchey »" in s.message_calcul("p1", {"statut": "annule"}, tmp_path)


def test_resultat_onf_dict_et_vide():
    assert s._resultat_onf({"ecartees": {"x": [1, 2, 3]}}).startswith("Résultat : 3 parcelles écartées du projet.")
    assert s._resultat_onf(None).startswith("Résultat : 0 parcelles écartées du projet.")


# ------------------------------------------------------------------ resoudre_projet

@pytest.fixture
def racine(tmp_path):
    projet_factice(tmp_path, "20261008_212542_uywc", "Couchey")
    projet_factice(tmp_path, "20261009_080000_aaaa", "Forêt d'Écouves")
    projet_factice(tmp_path, "20261010_080000_bbbb", "Forêt d'écouves")
    return tmp_path


def test_resoudre_par_identifiant(racine):
    assert s.resoudre_projet("20261008_212542_uywc", racine) == {"id": "20261008_212542_uywc", "nom": "Couchey"}


def test_resoudre_par_nom_exact_normalise(racine):
    assert s.resoudre_projet("  COUCHEY ", racine) == {"id": "20261008_212542_uywc", "nom": "Couchey"}


def test_resoudre_nom_partiel_delegue_sans_approche(racine):
    r = s.resoudre_projet("couch", racine)
    assert r["deleguer"] is True and "pas de projet au nom exact" in r["erreur"]


def test_resoudre_nom_partiel_avec_approche(racine):
    assert s.resoudre_projet("couch", racine, approche=True)["id"] == "20261008_212542_uywc"


def test_resoudre_aucune_correspondance_avec_approche(racine):
    r = s.resoudre_projet("zzz", racine, approche=True)
    assert r == {"erreur": "aucun projet ne correspond à « zzz »"}


def test_resoudre_plusieurs_candidats(racine):
    r = s.resoudre_projet("foret d ecouves", racine)
    assert r["erreur"] == "plusieurs projets correspondent"
    assert r["candidats"] == ["Forêt d'Écouves (20261009_080000_aaaa)", "Forêt d'écouves (20261010_080000_bbbb)"]


def test_resoudre_projet_vide(racine):
    assert s.resoudre_projet("   ", racine) == {"erreur": "projet non précisé"}


def test_resoudre_racine_vide_ou_inexistante(tmp_path):
    assert "deleguer" in s.resoudre_projet("x", tmp_path / "absent")


def test_resoudre_metadata_illisible_utilise_l_id(tmp_path):
    d = tmp_path / "p1"
    d.mkdir()
    (d / "metadata.json").write_text("{cassé", encoding="utf-8")
    assert s.resoudre_projet("p1", tmp_path) == {"id": "p1", "nom": "p1"}


# ------------------------------------------------------------------ contrat lu des fichiers amont
# Contrat lu, à confirmer avec le projet en amont : compute_job.json est écrit par
# nemetonshiny ; l'exemple ci-dessous est écrit à la main d'après ce que lit server.py.

def test_contrat_compute_job_json_lu_par_scan_calculs(tmp_path):
    projet_factice(tmp_path, "p1", "Couchey")
    exemple = {"job_id": "j-42", "statut": "termine", "type": "rapport", "pid": 1,
               "lance_a": "2026-11-10T10:00:00", "fin_a": "2026-11-10T10:05:00",
               "resultat": None, "erreur": None}
    (tmp_path / "p1" / "data" / "compute_job.json").write_text(json.dumps(exemple), encoding="utf-8")
    assert s.scan_calculs(tmp_path) == {"p1": {
        "job_id": "j-42", "statut": "termine", "type": "rapport", "resultat": None,
        "fin_a": "2026-11-10T10:05:00", "erreur": None}}


def test_contrat_compute_job_type_inconnu_vaut_calcul():
    assert s.type_job({"type": "autre"}) == "calcul"
    assert s.type_job({}) == "calcul"
    assert s.type_job("pas un dict") == "calcul"
