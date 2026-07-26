"""Ingestion de documents reglementaires dans le corpus editorial."""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

# Decoupage par en-tete d article (Art. / Article / Art )
_RE_ARTICLE = re.compile(
    r"^(Art(?:icle)?\.?\s*)(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
# Reference CGI : 18 G, 18-A, 36 bis, 18 sexies, 18 A 3° — sinon premier token (DEMO-18-G)
_RE_LATIN = (
    r"bis|ter|quater|quinquies|sexies|septies|octies|nonies|"
    r"decies|undecies|duodecies"
)
_RE_REFERENCE = re.compile(
    r"^("
    r"\d+"
    rf"(?:\s*(?:{_RE_LATIN}))?"
    r"(?:\s*[-–.]?\s*[A-Za-z])?"
    r"(?:\s*\d+\s*°)?"
    r")",
    re.IGNORECASE,
)

TAILLE_FRAGMENT = 500


@dataclass(frozen=True)
class ResultatIngestion:
    source_document_id: int
    articles: int
    fragments: int


def _decouper_articles(texte_brut: str) -> list[tuple[str, str, str]]:
    """Retourne [(reference, titre, texte_article), ...].

    Decoupe sur les lignes `Art.` / `Article`, sinon par paragraphes.
    """
    texte = texte_brut.strip()
    if not texte:
        return []

    matches = list(_RE_ARTICLE.finditer(texte))
    if not matches:
        # Repli : paragraphes separes par ligne vide
        blocs = [b.strip() for b in re.split(r"\n\s*\n", texte) if b.strip()]
        resultat: list[tuple[str, str, str]] = []
        for i, bloc in enumerate(blocs, start=1):
            premiere = bloc.split("\n", 1)[0][:120]
            ref = f"PARAG-{i}"
            resultat.append((ref, premiere, bloc))
        return resultat

    resultat = []
    for i, m in enumerate(matches):
        debut = m.start()
        fin = matches[i + 1].start() if i + 1 < len(matches) else len(texte)
        bloc = texte[debut:fin].strip()
        reste = m.group(2).strip()
        # Reference = numero + lettre/alinea si present (ex. 18 G), sinon token (DEMO-18-G)
        m_ref = _RE_REFERENCE.match(reste)
        if m_ref:
            reference = re.sub(r"\s+", " ", m_ref.group(1).strip())
        else:
            parts = reste.split(None, 1)
            reference = parts[0].rstrip(".—-–:") if parts else f"ART-{i + 1}"
        titre = reste[:200] if reste else reference
        # Corps = tout le bloc (en-tete inclus pour citation)
        resultat.append((reference, titre, bloc))
    return resultat


def _fragmenter(texte: str, taille: int = TAILLE_FRAGMENT) -> list[str]:
    """Decoupe un article en fragments ~taille caracteres, sans couper au milieu d un mot."""
    texte = texte.strip()
    if not texte:
        return []
    if len(texte) <= taille:
        return [texte]

    fragments: list[str] = []
    debut = 0
    while debut < len(texte):
        fin = min(debut + taille, len(texte))
        if fin < len(texte):
            # Remonter au dernier espace pour ne pas couper un mot
            espace = texte.rfind(" ", debut, fin)
            if espace > debut:
                fin = espace
        chunk = texte[debut:fin].strip()
        if chunk:
            fragments.append(chunk)
        debut = fin if fin > debut else fin + 1
    return fragments


def ingerer_document(
    session: Session,
    titre: str,
    type: str,
    millesime: int | None,
    texte_brut: str,
    *,
    fichier_uri: str | None = None,
) -> ResultatIngestion:
    """Insere source_document + article_corpus + fragment_corpus.

    ``fichier_uri`` optionnel (chemin local ou URL source) — traçabilité éditoriale.
    N'écrit aucune règle fiscale. Ne purge aucun ``a_confirmer``.
    """
    source_id = session.execute(
        text(
            "INSERT INTO source_document (titre, type, millesime, fichier_uri) "
            "VALUES (:titre, :type, :millesime, :uri) RETURNING id"
        ),
        {
            "titre": titre,
            "type": type,
            "millesime": millesime,
            "uri": fichier_uri,
        },
    ).scalar_one()

    articles = _decouper_articles(texte_brut)
    n_fragments = 0
    for reference, titre_art, corps in articles:
        article_id = session.execute(
            text(
                "INSERT INTO article_corpus "
                "(source_document_id, reference, titre, texte) "
                "VALUES (:sid, :ref, :titre, :texte) "
                "ON CONFLICT (source_document_id, reference) DO UPDATE "
                "SET titre = EXCLUDED.titre, texte = EXCLUDED.texte "
                "RETURNING id"
            ),
            {
                "sid": source_id,
                "ref": reference,
                "titre": titre_art,
                "texte": corps,
            },
        ).scalar_one()

        # Remplace les fragments existants en cas de re-ingestion conflict
        session.execute(
            text("DELETE FROM fragment_corpus WHERE article_id = :aid"),
            {"aid": article_id},
        )
        for rang, frag in enumerate(_fragmenter(corps)):
            session.execute(
                text(
                    "INSERT INTO fragment_corpus (article_id, contenu, rang) "
                    "VALUES (:aid, :contenu, :rang)"
                ),
                {"aid": article_id, "contenu": frag, "rang": rang},
            )
            n_fragments += 1

    session.flush()
    return ResultatIngestion(
        source_document_id=int(source_id),
        articles=len(articles),
        fragments=n_fragments,
    )


TEXTE_DEMO = """\
Article DEMO-18-G — [DÉMO FICTIF] Article DEMO-18-G — texte non opposable

Les dons et liberalites mentionnes au present article fictif sont admis en deduction
dans la limite d un plafond demontre. Ce texte est exclusivement destine aux essais
techniques de la plateforme. Il ne constitue pas une disposition du CGI et n est
pas opposable a l administration fiscale. Toute citation doit porter la mention
DÉMO FICTIF.

Article DEMO-42-A — [DÉMO FICTIF] Article DEMO-42-A — texte non opposable

En matiere de charges de personnel fictives pour tests, les sommes versees au titre
de primes exceptionnelles font l objet d une verification documentaire. Reference
demo uniquement. Aucun taux, seuil ou plafond legal n est affirme ici.

Article DEMO-99-Z — [DÉMO FICTIF] Article DEMO-99-Z — texte non opposable

Disposition de cloture demontree pour l indexation et la recherche hybride.
Vocabulaire distinct : abattement forfaitaire experimental, regime de report
deficitaire fictif. Texte non opposable.
"""


def seed_corpus_demo(session: Session) -> ResultatIngestion | None:
    """Insere le document DEMO s il n existe pas encore."""
    existe = session.execute(
        text(
            "SELECT id FROM source_document "
            "WHERE titre = :t AND type = 'demo' LIMIT 1"
        ),
        {"t": "[DÉMO FICTIF] Corpus de reference technique"},
    ).scalar_one_or_none()
    if existe is not None:
        return None
    return ingerer_document(
        session,
        titre="[DÉMO FICTIF] Corpus de reference technique",
        type="demo",
        millesime=2026,
        texte_brut=TEXTE_DEMO,
    )
