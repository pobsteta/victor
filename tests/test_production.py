"""Tests de caractérisation de production.py, sur un kit factice dans tmp_path."""
import json

import pytest

import production as p


@pytest.fixture
def kit(tmp_path):
    return tmp_path / "kit"


def ligne(etape, action, statut, detail=""):
    return p.journaliser(etape, action, statut, detail, kit=ligne.kit)


@pytest.fixture(autouse=True)
def _kit_courant(kit):
    ligne.kit = kit


# ------------------------------------------------------------------ journal

def test_journaliser_ecrit_une_ligne_et_cree_le_dossier(kit):
    l = p.journaliser(0, "demarrer", "ok", "projet=abc", kit=kit)
    champs = l.split(" | ")
    assert champs[1:] == ["S0", "demarrer", "OK", "projet=abc"]
    assert (kit / "captures" / "journal.txt").read_text(encoding="utf-8") == l + "\n"


def test_journaliser_en_ajout_seul(kit):
    ligne(0, "a", "OK")
    ligne(1, "b", "OK")
    assert len((kit / "captures" / "journal.txt").read_text().splitlines()) == 2


def test_journaliser_refuse_etape_ou_statut_inconnus(kit):
    with pytest.raises(ValueError, match="étape inconnue"):
        p.journaliser(8, "x", "OK", kit=kit)
    with pytest.raises(ValueError, match="statut inconnu"):
        p.journaliser(1, "x", "PEUT-ETRE", kit=kit)


def test_journaliser_nettoie_les_champs(kit):
    l = p.journaliser(1, "une | action\nlongue", "OK", "détail | avec\n  séparateur", kit=kit)
    assert len(l.split(" | ")) == 5
    assert "une / action longue" in l
    assert l.endswith("détail / avec séparateur")


def test_journaliser_action_vide_devient_note(kit):
    assert " | note | " in p.journaliser(1, "  ", "OK", kit=kit)


def test_journaliser_tronque_action_et_detail(kit):
    l = p.journaliser(1, "a" * 100, "OK", "d" * 500, kit=kit)
    champs = l.split(" | ")
    assert len(champs[2]) == 40 and len(champs[4]) == 200


def test_lire_journal_absent(kit):
    assert p.lire_journal(kit) == []


def test_lire_journal_ignore_les_lignes_mal_formees(kit):
    ligne(2, "x", "OK", "a | b")
    j = kit / "captures" / "journal.txt"
    with open(j, "a", encoding="utf-8") as f:
        f.write("n'importe quoi\n2026-01-01T00:00:00 | S9 | x | OK | hors plage\n")
    lus = p.lire_journal(kit)
    assert len(lus) == 1
    assert lus[0]["etape"] == 2 and lus[0]["detail"] == "a / b"


# ------------------------------------------------------------------ état

def test_etat_production_journal_vide(kit):
    e = p.etat_production(kit)
    assert e["projet"] is None
    assert e["etapes_faites"] == []
    assert e["prochaine_etape"] == 0
    assert e["arretee"] is False and e["erreur"] is None
    assert e["dernieres_lignes"] == []


def test_etat_production_suit_les_etapes_terminees_et_le_projet(kit):
    ligne(0, "demarrer", "OK", "projet=20261008_212542_uywc")
    ligne(0, "etape_terminee", "OK")
    ligne(1, "etape_terminee", "OK")
    e = p.etat_production(kit)
    assert e["projet"] == "20261008_212542_uywc"
    assert e["etapes_faites"] == [0, 1]
    assert e["prochaine_etape"] == 2
    assert e["prochaine"] == p.ETAPES[2]
    assert e["arretee"] is False


def test_etat_production_arretee_sur_erreur_puis_reprise(kit):
    ligne(0, "etape_terminee", "OK")
    ligne(1, "capture", "ERREUR", "écran noir")
    e = p.etat_production(kit)
    assert e["arretee"] is True
    assert e["erreur"] == "S1 capture : écran noir"
    ligne(1, "reprise", "OK")
    assert p.etat_production(kit)["arretee"] is False


def test_etat_production_terminee(kit):
    for n in p.ETAPES:
        ligne(n, "etape_terminee", "OK")
    e = p.etat_production(kit)
    assert e["prochaine_etape"] is None
    assert e["prochaine"] == "production terminée"


def test_etat_production_dernieres_lignes_limitees_a_cinq(kit):
    for i in range(8):
        ligne(1, f"note{i}", "OK")
    assert len(p.etat_production(kit)["dernieres_lignes"]) == 5


def test_etape_terminee_en_attente_ne_compte_pas(kit):
    ligne(0, "etape_terminee", "ATTENTE")
    assert p.etat_production(kit)["etapes_faites"] == []


# ------------------------------------------------------------------ fichiers

def test_fichiers_journalises_ok_seulement_sans_doublon(kit):
    ligne(1, "capture", "OK", "fichier=01-a.png")
    ligne(1, "capture", "OK", "fichier=01-a.png")
    ligne(1, "capture", "ERREUR", "fichier=02-b.png")
    ligne(2, "capture", "OK", "fichier=03-c.webm taille=3")
    assert p.fichiers_journalises(kit) == ["01-a.png", "03-c.webm"]


# ------------------------------------------------------------------ timecodes

@pytest.mark.parametrize("entree, attendu", [("6:15", "00:06:15"), ("0:00", "00:00:00"),
                                             ("1:02:03", "01:02:03"), ("45", "00:00:45")])
def test_tc(entree, attendu):
    assert p._tc(entree) == attendu


def test_timecodes_par_defaut_sans_fichier(kit):
    tcs = p.timecodes(kit)
    assert sorted(tcs) == list(range(1, 9))
    assert tcs[1] == ("00:00:00", "00:00:35")
    assert tcs[8] == ("00:07:30", "00:08:00")


def test_timecodes_lus_dans_prompts_voix_off(kit):
    kit.mkdir()
    (kit / "prompts-voix-off.md").write_text(
        "## Séquence 1 (0:00 → 0:20)\ntexte\n## Séquence 2 (0:20 → 1:10)\n", encoding="utf-8")
    assert p.timecodes(kit) == {1: ("00:00:00", "00:00:20"), 2: ("00:00:20", "00:01:10")}


# ------------------------------------------------------------------ séquences & rushes

@pytest.mark.parametrize("nom, seq", [
    ("07-radar.png", 7), ("03-install.webm", 3), ("video-nemetonshiny-2026.webm", 7),
    ("S5.mp4", 5), ("autre.png", None),
])
def test_sequence_de(nom, seq):
    assert p._sequence_de(nom) == seq


def test_sequence_de_ignore_le_dossier():
    assert p._sequence_de("captures/04-demo.png") == 4


def test_rush_pret(kit):
    (kit / "rushes").mkdir(parents=True)
    assert p.rush_pret(3, kit) is None
    (kit / "rushes" / "S3.mp4").write_bytes(b"")
    (kit / "rushes" / "S3.mov").write_bytes(b"")
    assert p.rush_pret(3, kit).name == "S3.mov"  # le premier dans l'ordre alphabétique


def test_resume_rushes(kit):
    (kit / "rushes").mkdir(parents=True)
    (kit / "rushes" / "S1.mp4").write_bytes(b"")
    ligne(1, "capture", "OK", "fichier=01-a.png")
    (kit / "captures" / "02-b.webm").write_bytes(b"")
    (kit / "captures" / "journal.txt.bak").write_text("ignoré")
    chemin, manquants = p.resume_rushes(kit)
    assert chemin == kit / "captures" / "resume-rushes.txt"
    assert manquants == [f"S{n}" for n in range(2, 9)]
    lignes = chemin.read_text(encoding="utf-8").splitlines()
    assert lignes[0].startswith("# Liste de courses")
    # L'en-tête ne contient aucun motif S<chiffre> (lu par assemblage-ffmpeg.sh).
    assert not any(__import__("re").search(r"S\d", l) for l in lignes[:2])
    s1 = next(l for l in lignes if l.startswith("S1 |"))
    assert "rush=rushes/S1.mp4" in s1 and "01-a.png" in s1
    s2 = next(l for l in lignes if l.startswith("S2 |"))
    assert "rush=MANQUANT" in s2 and "02-b.webm" in s2
    s3 = next(l for l in lignes if l.startswith("S3 |"))
    assert "captures=aucune" in s3


# ------------------------------------------------------------------ indicateurs

def test_nombres_annonces_voix_off_et_srt_sans_version_anglaise(kit):
    kit.mkdir()
    (kit / "prompts-voix-off.md").write_text(
        "Il calcule 41 indicateurs.\n## Version anglaise\n99 indicateurs", encoding="utf-8")
    (kit / "sous-titres.srt").write_text("1\n00:00:00 --> 00:00:02\n41 au total, 12 sous-indicateurs", encoding="utf-8")
    assert p.nombres_annonces(kit) == [12, 41]


def test_nombres_annonces_sans_fichiers(kit):
    assert p.nombres_annonces(kit) == []


def ecrire_progression(racine, projet, contenu):
    d = racine / projet / "data"
    d.mkdir(parents=True)
    (d / "progress_state.json").write_text(contenu, encoding="utf-8")


def test_nombre_reel(tmp_path):
    ecrire_progression(tmp_path, "p1", json.dumps({"indicators_total": 41}))
    ecrire_progression(tmp_path, "p2", "pas du json")
    ecrire_progression(tmp_path, "p3", json.dumps({"indicators_total": 0}))
    ecrire_progression(tmp_path, "p4", json.dumps({"indicators_total": True}))
    assert p.nombre_reel("p1", tmp_path) == 41
    assert p.nombre_reel("p2", tmp_path) is None
    assert p.nombre_reel("p3", tmp_path) is None
    assert p.nombre_reel("p4", tmp_path) == 1  # caractérisation : bool est un int en Python
    assert p.nombre_reel("absent", tmp_path) is None


def test_verifier_indicateurs_coherent(kit, tmp_path):
    kit.mkdir()
    (kit / "prompts-voix-off.md").write_text("41 indicateurs", encoding="utf-8")
    ecrire_progression(tmp_path, "p1", json.dumps({"indicators_total": 41}))
    r = p.verifier_indicateurs("p1", tmp_path, kit)
    assert r == {"annonces": [41], "reel": 41, "coherent": True, "avis": "cohérent : 41 indicateurs"}


def test_verifier_indicateurs_incoherent(kit, tmp_path):
    kit.mkdir()
    (kit / "prompts-voix-off.md").write_text("31 indicateurs", encoding="utf-8")
    ecrire_progression(tmp_path, "p1", json.dumps({"indicators_total": 41}))
    r = p.verifier_indicateurs("p1", tmp_path, kit)
    assert r["coherent"] is False
    assert r["avis"] == "incohérent : la voix off dit 31, le calcul en compte 41"


def test_verifier_indicateurs_reel_inconnu(kit, tmp_path):
    r = p.verifier_indicateurs(None, tmp_path, kit)
    assert r["reel"] is None and r["coherent"] is False
    assert r["avis"].startswith("nombre réel inconnu")


def test_verifier_indicateurs_rien_dans_la_voix_off(kit, tmp_path):
    kit.mkdir()
    ecrire_progression(tmp_path, "p1", json.dumps({"indicators_total": 41}))
    r = p.verifier_indicateurs("p1", tmp_path, kit)
    assert r["coherent"] is False
    assert r["avis"] == "aucun nombre d'indicateurs trouvé dans la voix off"


# ------------------------------------------------------------------ assemblage

def test_manquants_assemblage_sans_resume(kit):
    m = p.manquants_assemblage(kit)
    assert m["sequences"] == [f"S{n}" for n in range(1, 9)]
    assert m["voix"] == m["sequences"] and m["rushes"] == m["sequences"]
    assert m["srt"] is False


def test_manquants_assemblage_avec_resume(kit):
    (kit / "voix").mkdir(parents=True)
    (kit / "rushes").mkdir()
    (kit / "captures").mkdir()
    (kit / "captures" / "resume-rushes.txt").write_text("S2 | x\nS4 | y\nS2 | z\n", encoding="utf-8")
    (kit / "voix" / "S2.mp3").write_bytes(b"")
    (kit / "rushes" / "S4.mp4").write_bytes(b"")
    (kit / "sous-titres.srt").write_text("", encoding="utf-8")
    assert p.manquants_assemblage(kit) == {"sequences": ["S2", "S4"], "voix": ["S4"],
                                           "rushes": ["S2"], "srt": True}
