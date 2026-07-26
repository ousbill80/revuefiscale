"""API — point d entree."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.abonne.paystack import router_webhooks as router_webhooks_paystack
from backend.abonne.routes import router as router_abonne
from backend.abonne.routes import router_client
from backend.agent.routes import (
    router_agent,
    router_propositions,
    router_usages,
)
from backend.billing.routes import router as router_billing
from backend.config import config
from backend.corpus.routes import router as router_corpus
from backend.editorial.routes import router as router_editorial
from backend.moteur.routes import router as router_moteur
from backend.plateforme.inscription_routes import (
    router_inscription,
    router_onboarding,
)
from backend.plateforme.routes import router as router_plateforme
from backend.restitution.routes import router as router_restitution
from backend.socle.routes import router as router_socle

if config.env != "dev" and not config.secret_key:
    raise RuntimeError("SECRET_KEY est obligatoire hors environnement de developpement")

RACINE = Path(__file__).resolve().parents[1]

app = FastAPI(
    title="Plateforme de revue fiscale",
    description="SaaS multi-cabinets — CGI 2026, Cote d Ivoire",
    version="0.1.0",
)

app.include_router(router_plateforme)
app.include_router(router_inscription)
app.include_router(router_onboarding)
app.include_router(router_abonne)
app.include_router(router_client)
app.include_router(router_webhooks_paystack)
app.include_router(router_billing)
app.include_router(router_socle)
app.include_router(router_editorial)
app.include_router(router_corpus)
app.include_router(router_moteur)
app.include_router(router_restitution)
app.include_router(router_agent)
app.include_router(router_propositions)
app.include_router(router_usages)


@app.get("/sante")
def sante() -> dict[str, object]:
    """Santé + (ENV=dev seulement) indices démo cabinet — jamais hors dev."""
    from backend.socle.poppler_outils import etat_poppler

    corps: dict[str, object] = {
        "statut": "ok",
        "env": config.env,
        "poppler": etat_poppler(),
        "pieces_session_ttl_heures": config.pieces_session_ttl_hours,
    }
    if config.env == "dev":
        corps["demo"] = {
            "email": config.cabinet_demo_email.strip().lower(),
            "mot_de_passe": config.cabinet_demo_password,
            "rejouer": "make demolot",
            "hint": "Cabinet isolé + mission FICTIF — make seed && make demolot",
        }
    return corps


@app.get("/admin")
@app.get("/admin/{chemin:path}")
def rediriger_admin_vers_console(chemin: str = "") -> RedirectResponse:
    """Anciens signets /admin → /console (S0)."""
    cible = f"/console/{chemin}" if chemin else "/console/"
    return RedirectResponse(url=cible, status_code=308)


# UI mission : dist Vite (React) si buildé, sinon HTML statique de secours.
_mission_dist = RACINE / "frontend" / "mission" / "dist"
_app_statique = (
    _mission_dist if (_mission_dist / "index.html").is_file() else RACINE / "frontend" / "app"
)
app.mount(
    "/app",
    StaticFiles(directory=str(_app_statique), html=True),
    name="app",
)
app.mount(
    "/console",
    StaticFiles(directory=str(RACINE / "frontend" / "admin"), html=True),
    name="console",
)
app.mount(
    "/billing",
    StaticFiles(directory=str(RACINE / "frontend" / "billing"), html=True),
    name="billing",
)
app.mount(
    "/client",
    StaticFiles(directory=str(RACINE / "frontend" / "client"), html=True),
    name="client",
)
app.mount(
    "/shared",
    StaticFiles(directory=str(RACINE / "frontend" / "shared")),
    name="shared",
)
# Landing marketing — mount `/` en dernier pour ne pas masquer /app, /api, /console, etc.
app.mount(
    "/",
    StaticFiles(directory=str(RACINE / "frontend" / "landing"), html=True),
    name="landing",
)
