"""Barrières de clôture : conclusions évaluées + anomalies validées (A1/A2)."""
from __future__ import annotations

import uuid

import pytest

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
    from backend.editorial.publication import creer_version_brouillon, publier_version

    lib = f"v-cloture-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="cloture-gardes")
    publier_version(session, lib, "cloture@test.ci")


def _mission_en_cours(session) -> tuple[int, int]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"clot.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Clot {email}",
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
                "VALUES (:t, 'PM Clot FICTIF', 'pm') RETURNING id"
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
    return r.tenant_id, int(mid)


def _regle_version_id(session) -> int:
    rv = session.execute(
        text("SELECT id FROM regle_version ORDER BY id LIMIT 1")
    ).scalar_one_or_none()
    if rv is not None:
        return int(rv)
    vr = session.execute(
        text("SELECT id FROM version_referentiel ORDER BY id DESC LIMIT 1")
    ).scalar_one()
    ident = f"TEST_CLOT_{uuid.uuid4().hex[:8].upper()}"
    session.execute(
        text(
            "INSERT INTO regle (identifiant, impot, libelle) "
            "VALUES (:i, 'BIC', 'Règle test clôture')"
        ),
        {"i": ident},
    )
    return int(
        session.execute(
            text(
                "INSERT INTO regle_version (regle_id, version_referentiel_id, "
                "reference_article, reference_source, millesime, date_effet, "
                "nature, condition_declenchement, expression_resultat, "
                "niveau_risque) "
                "VALUES (:r, :v, 'art. test', 'test', 2025, '2025-01-01', "
                "'reintegration', 'true', '0', 'moyen') RETURNING id"
            ),
            {"r": ident, "v": vr},
        ).scalar_one()
    )


def _creer_conclusion(
    session, tenant_id: int, mission_id: int, *, statut: str = "anomalie"
) -> int:
    rv = _regle_version_id(session)
    with contexte_tenant(session, tenant_id):
        eid = session.execute(
            text(
                "INSERT INTO execution (tenant_id, mission_id, lancee_par) "
                "VALUES (:t, :m, 'test@cloture') RETURNING id"
            ),
            {"t": tenant_id, "m": mission_id},
        ).scalar_one()
        return int(
            session.execute(
                text(
                    "INSERT INTO conclusion (tenant_id, execution_id, "
                    "regle_version_id, niveau_risque, statut) "
                    "VALUES (:t, :e, :rv, 'moyen', :st) RETURNING id"
                ),
                {"t": tenant_id, "e": eid, "rv": rv, "st": statut},
            ).scalar_one()
        )


def test_mission_sans_conclusion_cloturable(session):
    from backend.plateforme.missions import changer_statut_mission

    tid, mid = _mission_en_cours(session)
    r = changer_statut_mission(session, tid, mid, "cloturee")
    assert r["statut"] == "cloturee"


def test_conclusion_non_evaluee_bloque_cloture(session):
    from backend.plateforme.missions import ErreurMission, changer_statut_mission

    tid, mid = _mission_en_cours(session)
    _creer_conclusion(session, tid, mid, statut="anomalie")
    with pytest.raises(ErreurMission) as exc:
        changer_statut_mission(session, tid, mid, "cloturee")
    msg = str(exc.value)
    assert "Clôture refusée" in msg
    assert "non évaluée(s)" in msg


def test_anomalie_evaluee_non_validee_bloque_cloture(session):
    from backend.plateforme.conclusions import patcher_conclusion
    from backend.plateforme.missions import ErreurMission, changer_statut_mission

    tid, mid = _mission_en_cours(session)
    cid = _creer_conclusion(session, tid, mid, statut="anomalie")
    patcher_conclusion(
        session, tid, mid, cid, acteur="reviseur@test.ci", statut="anomalie"
    )
    with pytest.raises(ErreurMission) as exc:
        changer_statut_mission(session, tid, mid, "cloturee")
    msg = str(exc.value)
    assert "anomalie(s) non validée(s)" in msg


def test_validation_refusee_sur_brouillon(session):
    from backend.plateforme.conclusions import ErreurConclusion, valider_conclusion

    tid, mid = _mission_en_cours(session)
    cid = _creer_conclusion(session, tid, mid, statut="anomalie")
    with pytest.raises(ErreurConclusion) as exc:
        valider_conclusion(session, tid, mid, cid, validateur="assoc@test.ci")
    assert "non évaluée" in str(exc.value)


def test_validation_puis_cloture_ok(session):
    from backend.plateforme.conclusions import patcher_conclusion, valider_conclusion
    from backend.plateforme.missions import changer_statut_mission

    tid, mid = _mission_en_cours(session)
    cid = _creer_conclusion(session, tid, mid, statut="anomalie")
    patcher_conclusion(
        session, tid, mid, cid, acteur="reviseur@test.ci", statut="anomalie"
    )
    c = valider_conclusion(session, tid, mid, cid, validateur="assoc@test.ci")
    assert c["valide_par"] == "assoc@test.ci"
    assert c["valide_le"]
    r = changer_statut_mission(session, tid, mid, "cloturee")
    assert r["statut"] == "cloturee"


def test_conclusion_evaluee_conforme_cloturable(session):
    from backend.plateforme.conclusions import patcher_conclusion
    from backend.plateforme.missions import changer_statut_mission

    tid, mid = _mission_en_cours(session)
    cid = _creer_conclusion(session, tid, mid, statut="anomalie")
    patcher_conclusion(
        session, tid, mid, cid, acteur="reviseur@test.ci", statut="conforme"
    )
    r = changer_statut_mission(session, tid, mid, "cloturee")
    assert r["statut"] == "cloturee"


def test_reamendement_invalide_la_validation(session):
    from backend.plateforme.conclusions import patcher_conclusion, valider_conclusion

    tid, mid = _mission_en_cours(session)
    cid = _creer_conclusion(session, tid, mid, statut="anomalie")
    patcher_conclusion(
        session, tid, mid, cid, acteur="reviseur@test.ci", statut="anomalie"
    )
    valider_conclusion(session, tid, mid, cid, validateur="assoc@test.ci")
    c = patcher_conclusion(
        session, tid, mid, cid, acteur="reviseur@test.ci", statut="sous_seuil"
    )
    assert c["valide_par"] is None
    assert c["valide_le"] is None
