"""Extension du dossier de synthèse — blocs « completude_declarative »
(15e bloc) et « coherence_ca » (16e bloc), facultatifs, SYNTHÉTIQUES :
projections des contrôles de conformité consultatifs, aucun recalcul."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.dossier_mission import (
    BLOCS_DOSSIER,
    assembler_dossier,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_blocs_conformite_declares_dans_blocs_dossier():
    assert "completude_declarative" in BLOCS_DOSSIER
    assert "coherence_ca" in BLOCS_DOSSIER


def test_assembler_dossier_blocs_conformite_manquants_valent_none():
    # Assemblage sans les blocs : clés présentes, valeurs None
    # (contrat stable côté frontend).
    dossier = assembler_dossier({"identite": {"mission_id": 1}})
    assert "completude_declarative" in dossier
    assert dossier["completude_declarative"] is None
    assert "coherence_ca" in dossier
    assert dossier["coherence_ca"] is None
    assert dossier["blocs_disponibles"] == 1


def test_assembler_dossier_blocs_conformite_presents_comptes():
    bloc_cd = {
        "exercice": 2025,
        "synthese": {"statut_global": "lacunaire", "nb_manquantes_total": 3},
        "impots": {
            "tva": {
                "statut": "lacunaire",
                "nb_manquantes": 2,
                "taux_couverture": "83.3",
            },
            "salaires": {
                "statut": "lacunaire",
                "nb_manquantes": 1,
                "taux_couverture": "91.7",
            },
        },
        "note": "n",
    }
    bloc_ca = {
        "statut": "coherent",
        "ca_comptable": "100000000",
        "ca_reconstitue": "100000000.00",
        "ecart": "0.00",
        "ecart_relatif_pct": "0.0",
        "approximation": True,
        "note": "n",
    }
    dossier = assembler_dossier(
        {
            "identite": {"mission_id": 1},
            "completude_declarative": bloc_cd,
            "coherence_ca": bloc_ca,
        }
    )
    assert dossier["completude_declarative"] == bloc_cd
    assert dossier["coherence_ca"] == bloc_ca
    assert dossier["blocs_disponibles"] == 3


def test_assembler_dossier_blocs_conformite_non_dict_neutralises():
    dossier = assembler_dossier(
        {
            "identite": {"mission_id": 1},
            "completude_declarative": "n/a",
            "coherence_ca": ["n/a"],
        }
    )
    assert dossier["completude_declarative"] is None
    assert dossier["coherence_ca"] is None
    assert dossier["blocs_disponibles"] == 1


# ── Tests API / DB ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-dossier-conf-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="dossier-conformite")
    publier_version(session, lib, "dossier-conformite@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"dossier.conf.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Dossier Conformite {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    with contexte_tenant(session, r.tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, 'PM Dossier Conformite FICTIVE', 'pm') "
                "RETURNING id"
            ),
            {"t": r.tenant_id},
        ).scalar_one()
        mid = creer_mission(
            session,
            r.tenant_id,
            contribuable_id=int(cid),
            exercice=2025,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
        session.execute(
            text("UPDATE mission SET statut = 'en_cours' WHERE id = :m"),
            {"m": mid},
        )
    return r.tenant_id, int(mid), email


def _client_connecte(email: str):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    return client, {"Authorization": f"Bearer {login.json()['jeton']}"}


def test_api_dossier_contient_blocs_conformite_sans_donnees(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()

    # Complétude déclarative : clé TOUJOURS présente, bloc construit
    # même sans aucune saisie (exercice 2025 échu : 12 périodes
    # attendues par impôt, toutes manquantes).
    assert "completude_declarative" in corps
    cd = corps["completude_declarative"]
    assert cd is not None
    assert cd["exercice"] == 2025
    assert cd["synthese"]["statut_global"] == "aucune_saisie"
    assert cd["synthese"]["nb_manquantes_total"] == 24
    for impot in ("tva", "salaires"):
        assert cd["impots"][impot]["statut"] == "aucune_saisie"
        assert cd["impots"][impot]["nb_manquantes"] == 12
        assert cd["impots"][impot]["taux_couverture"] == "0.0"
    assert cd["note"]
    # Projection SYNTHÉTIQUE : ni détail des périodes ni références.
    assert "references" not in cd
    assert "attendues" not in cd["impots"]["tva"]

    # Cohérence CA : clé TOUJOURS présente, statut explicite sans
    # balance ni déclaration — aucun montant inventé.
    assert "coherence_ca" in corps
    ca = corps["coherence_ca"]
    assert ca is not None
    assert ca["statut"] == "indisponible"
    assert ca["ca_comptable"] == "0"
    assert ca["ca_reconstitue"] == "0"
    assert ca["ecart"] == "0"
    assert ca["ecart_relatif_pct"] is None
    assert ca["approximation"] is True
    assert ca["note"]
    # Projection SYNTHÉTIQUE : ni références ni détail des synthèses.
    assert "references" not in ca
    assert "synthese" not in ca


def test_api_dossier_coherence_ca_avec_balance_et_declaration(session):
    tid, mid, email = _mission_en_cours(session)
    with contexte_tenant(session, tid):
        session.execute(
            text(
                "INSERT INTO solde_compte "
                "(tenant_id, mission_id, compte, libelle, debit, credit) "
                "VALUES (:t, :m, '701000', 'Ventes FICTIVES', 0, 100000000)"
            ),
            {"t": tid, "m": mid},
        )
        session.execute(
            text(
                "INSERT INTO declaration_tva "
                "(tenant_id, mission_id, periode, tva_collectee) "
                "VALUES (:t, :m, '2025-01', 18000000)"
            ),
            {"t": tid, "m": mid},
        )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()

    # CA reconstitué = 18 000 000 ÷ 0,18 = 100 000 000 : cohérent.
    ca = corps["coherence_ca"]
    assert ca["statut"] == "coherent"
    assert ca["ca_comptable"] == "100000000.00"
    assert ca["ca_reconstitue"] == "100000000.00"
    assert ca["ecart"] == "0.00"
    assert ca["ecart_relatif_pct"] == "0.0"
    assert ca["approximation"] is True

    # Et la déclaration saisie couvre une période de complétude TVA.
    cd = corps["completude_declarative"]
    assert cd["impots"]["tva"]["statut"] == "lacunaire"
    assert cd["impots"]["tva"]["nb_manquantes"] == 11


def test_dossier_tolere_echec_du_module_completude_declarative(
    session, monkeypatch
):
    # Tolérance par bloc : un échec du module completude_declarative
    # donne un bloc None sans jamais bloquer la remise du dossier.
    import backend.plateforme.completude_declarative as module_cd
    from backend.plateforme.dossier_mission import dossier_mission

    tid, mid, _email = _mission_en_cours(session)
    session.commit()

    def _boom(*_a, **_k):
        raise RuntimeError("module completude_declarative en échec simulé")

    monkeypatch.setattr(
        module_cd, "completude_declarative_mission", _boom
    )
    dossier = dossier_mission(session, tid, mid)
    assert dossier["completude_declarative"] is None
    assert dossier["coherence_ca"] is not None
    assert dossier["identite"]["mission_id"] == mid
    assert dossier["note"]


def test_dossier_tolere_echec_du_module_coherence_ca(session, monkeypatch):
    # Tolérance par bloc : un échec du module coherence_ca donne un
    # bloc None sans jamais bloquer la remise du dossier.
    import backend.plateforme.coherence_ca as module_ca
    from backend.plateforme.dossier_mission import dossier_mission

    tid, mid, _email = _mission_en_cours(session)
    session.commit()

    def _boom(*_a, **_k):
        raise RuntimeError("module coherence_ca en échec simulé")

    monkeypatch.setattr(module_ca, "coherence_ca_mission", _boom)
    dossier = dossier_mission(session, tid, mid)
    assert dossier["coherence_ca"] is None
    assert dossier["completude_declarative"] is not None
    assert dossier["identite"]["mission_id"] == mid
    assert dossier["note"]
