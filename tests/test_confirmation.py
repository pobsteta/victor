"""Tests de caractérisation de confirmation.py : ce que le code fait aujourd'hui."""
import json

import pytest

import confirmation as c

# 2026-11-11T09:30:00Z
T_EXPIRE = 1_794_389_400.0


def bloc_valide(**surcharge):
    b = {"outil": "appliquer_ugf", "projet": "20261008_212542_uywc", "projet_nom": "Couchey",
         "jeton": "abc123", "expire_a": "2026-11-11T09:30:00Z", "arguments": {"ugf": 3}}
    b.update(surcharge)
    return b


def entoure(ligne: str) -> str:
    return f"{c.DEBUT}\n{ligne}\n{c.FIN}"


# ------------------------------------------------------------------ valider

def test_valider_accepte_un_bloc_complet():
    b = bloc_valide()
    assert c.valider(b) is b


@pytest.mark.parametrize("cle", c.CLES)
def test_valider_refuse_une_cle_manquante(cle):
    b = bloc_valide()
    del b[cle]
    assert c.valider(b) is None


@pytest.mark.parametrize("cle", ["outil", "projet", "projet_nom", "jeton", "expire_a"])
def test_valider_refuse_une_chaine_vide_ou_non_chaine(cle):
    assert c.valider(bloc_valide(**{cle: "  "})) is None
    assert c.valider(bloc_valide(**{cle: 12})) is None


def test_valider_refuse_non_dict():
    assert c.valider(None) is None
    assert c.valider([1]) is None


def test_valider_arguments_doivent_etre_un_dict_sans_jeton():
    assert c.valider(bloc_valide(arguments=[])) is None
    assert c.valider(bloc_valide(arguments={"jeton": "x"})) is None
    assert c.valider(bloc_valide(arguments={})) is not None


@pytest.mark.parametrize("outil", ["1abc", "a-b", "a b", "a.b"])
def test_valider_refuse_un_nom_d_outil_invalide(outil):
    assert c.valider(bloc_valide(outil=outil)) is None


def test_valider_refuse_une_date_illisible():
    assert c.valider(bloc_valide(expire_a="demain")) is None


# ------------------------------------------------------------------ expire

def test_expire_avant_et_apres():
    b = bloc_valide()
    assert c.expire(b, T_EXPIRE - 1) is False
    assert c.expire(b, T_EXPIRE) is True
    assert c.expire(b, T_EXPIRE + 1) is True


def test_expire_date_illisible_ou_absente_est_expiree():
    assert c.expire({"expire_a": "n'importe quoi"}, 0) is True
    assert c.expire({}, 0) is True


def test_expire_date_sans_fuseau_est_lue_en_utc():
    b = bloc_valide(expire_a="2026-11-11T09:30:00")
    assert c.expire(b, T_EXPIRE - 1) is False
    assert c.expire(b, T_EXPIRE) is True


def test_expire_sans_horloge_utilise_time_time(monkeypatch):
    monkeypatch.setattr(c.time, "time", lambda: T_EXPIRE + 5)
    assert c.expire(bloc_valide()) is True
    monkeypatch.setattr(c.time, "time", lambda: T_EXPIRE - 5)
    assert c.expire(bloc_valide()) is False


# ------------------------------------------------------------------ extraire

def test_extraire_sans_bloc_rend_le_texte_tel_quel():
    assert c.extraire("bonjour") == ("bonjour", None, None)
    assert c.extraire(None) == ("", None, None)


def test_extraire_retire_le_bloc_et_le_retient():
    ligne = json.dumps(bloc_valide())
    propre, bloc, brut = c.extraire(f"Avant\n{entoure(ligne)}\nAprès")
    assert "NEMETON_CONFIRMATION" not in propre
    assert "abc123" not in propre
    assert propre.startswith("Avant") and propre.endswith("Après")
    assert bloc == bloc_valide()
    assert brut == ligne


def test_extraire_garde_le_dernier_bloc_valide():
    un = json.dumps(bloc_valide(jeton="premier"))
    deux = json.dumps(bloc_valide(jeton="second"))
    _, bloc, brut = c.extraire(entoure(un) + "\n" + entoure(deux))
    assert bloc["jeton"] == "second"
    assert brut == deux


def test_extraire_bloc_invalide_est_retire_mais_pas_retenu():
    texte = "x\n" + entoure(json.dumps(bloc_valide(arguments={"jeton": "fuite"}))) + "\ny"
    propre, bloc, brut = c.extraire(texte)
    assert (bloc, brut) == (None, None)
    assert "fuite" not in propre


def test_extraire_bloc_json_casse_est_retire():
    propre, bloc, _ = c.extraire("a\n" + entoure("{pas du json") + "\nb")
    assert bloc is None
    assert "pas du json" not in propre


def test_extraire_balise_ouvrante_sans_fermeture_coupe_la_suite():
    propre, bloc, _ = c.extraire(f"début\n{c.DEBUT}\n" + '{"jeton": "secret"')
    assert propre == "début"
    assert bloc is None


# ------------------------------------------------------------------ prompts

def test_prompt_tache2_gabarit_exact():
    assert c.prompt_tache2("{ligne}") == (
        "L'utilisateur a confirmé oralement.\n<<<NEMETON_CONFIRMATION\n{ligne}\nNEMETON_CONFIRMATION>>>")


def test_prompt_tache2_est_relu_par_extraire():
    ligne = json.dumps(bloc_valide())
    _, bloc, brut = c.extraire(c.prompt_tache2(ligne))
    assert bloc == bloc_valide() and brut == ligne


def test_prompt_affiche_ne_montre_pas_le_jeton():
    assert c.prompt_affiche(bloc_valide()) == "[confirmation de appliquer_ugf sur Couchey]"


@pytest.mark.parametrize("texte", [c.DEBUT, c.FIN, c.PHRASE, f"x {c.PHRASE} y"])
def test_contient_confirmation_vrai(texte):
    assert c.contient_confirmation(texte) is True


def test_contient_confirmation_faux():
    assert c.contient_confirmation("rien de spécial") is False
    assert c.contient_confirmation("") is False
    assert c.contient_confirmation(None) is False


def test_resume_pour_voix_sans_jeton_ni_arguments():
    r = c.resume_pour_voix(bloc_valide())
    assert r == {"outil": "appliquer_ugf", "projet": "20261008_212542_uywc",
                 "projet_nom": "Couchey", "expire_a": "2026-11-11T09:30:00Z"}


# ------------------------------------------------------------------ Attentes

def test_attentes_garder_et_prendre_usage_unique():
    a = c.Attentes()
    b = bloc_valide()
    a.garder("t1", b, "brut")
    assert a.en_attente() == ["t1"]
    assert a.prendre("t1") == (b, "brut")
    assert a.prendre("t1") is None
    assert a.en_attente() == []


def test_attentes_prendre_inconnu():
    assert c.Attentes().prendre("nope") is None


def test_attentes_jeter_expires_avec_horloge_passee_en_parametre():
    a = c.Attentes()
    a.garder("vivant", bloc_valide(expire_a="2026-11-11T10:00:00Z"), "v")
    a.garder("mort", bloc_valide(expire_a="2026-11-11T09:00:00Z"), "m")
    maintenant = T_EXPIRE  # 09:30:00Z
    assert a.jeter_expires(maintenant) == ["mort"]
    assert a.en_attente() == ["vivant"]
    assert a.jeter_expires(maintenant) == []
