"""
API FastAPI — Pont entre Lovable et les scripts Python
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import json
import os
import sys

sys.path.append(os.path.dirname(__file__))

# Import des scripts avec leurs vrais noms
import importlib.util

def importer(nom_fichier, nom_module):
    spec = importlib.util.spec_from_file_location(nom_module, os.path.join(os.path.dirname(__file__), nom_fichier))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

ft = importer("1_france_travail.py", "france_travail")
ats = importer("2_ats_scraper.py", "ats_scraper")
ia = importer("3_ia_engine.py", "ia_engine")

app = FastAPI(title="JobAlert IA", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── MODÈLES ───

class CriteresRecherche(BaseModel):
    motsCles: str
    typeContrat: Optional[str] = ""
    distance: Optional[int] = 30
    nbResultats: Optional[int] = 20

class DemandeScoring(BaseModel):
    profil: dict
    offre: dict

class DemandeCV(BaseModel):
    profil: dict
    offre: dict
    cv_original: str

class DemandeLettre(BaseModel):
    profil: dict
    offre: dict

class AnalyseCV(BaseModel):
    texte_cv: str

class CandidatureUpdate(BaseModel):
    candidature_id: str
    statut: str

# ─── ROUTES ───

@app.get("/")
def root():
    return {"message": "JobAlert IA API — En ligne ✅"}

@app.post("/offres/france-travail")
def get_offres_france_travail(criteres: CriteresRecherche):
    try:
        offres = ft.rechercher_offres(criteres.dict())
        return {"success": True, "offres": offres, "total": len(offres)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/offres/ats")
def get_offres_ats(criteres: CriteresRecherche):
    try:
        offres = ats.scraper_tous_ats(mots_cles=criteres.motsCles)
        return {"success": True, "offres": offres, "total": len(offres)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/offres/toutes")
def get_toutes_offres(criteres: CriteresRecherche):
    try:
        offres_ft = ft.rechercher_offres(criteres.dict())
        offres_ats = ats.scraper_tous_ats(mots_cles=criteres.motsCles)
        toutes = offres_ft + offres_ats
        return {"success": True, "offres": toutes, "total": len(toutes)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ia/analyser-cv")
def route_analyser_cv(demande: AnalyseCV):
    try:
        profil = ia.analyser_cv(demande.texte_cv)
        return {"success": True, "profil": profil}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ia/scorer")
def route_scorer(demande: DemandeScoring):
    try:
        score = ia.scorer_compatibilite(demande.profil, demande.offre)
        return {"success": True, "score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ia/lettre")
def route_lettre(demande: DemandeLettre):
    try:
        lettre = ia.generer_lettre_motivation(demande.profil, demande.offre)
        return {"success": True, "lettre": lettre}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ia/package-complet")
def route_package_complet(demande: DemandeCV):
    try:
        score = ia.scorer_compatibilite(demande.profil, demande.offre)
        cv_adapte = ia.adapter_cv(demande.profil, demande.offre, demande.cv_original)
        lettre = ia.generer_lettre_motivation(demande.profil, demande.offre)
        return {"success": True, "score": score, "cv_adapte": cv_adapte, "lettre": lettre}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/candidatures/{user_id}")
def get_candidatures(user_id: str):
    try:
        fichier = f"candidatures_{user_id}.json"
        if not os.path.exists(fichier):
            return {"success": True, "candidatures": []}
        with open(fichier, "r", encoding="utf-8") as f:
            candidatures = json.load(f)
        return {"success": True, "candidatures": candidatures}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats/{user_id}")
def get_stats(user_id: str):
    try:
        fichier = f"candidatures_{user_id}.json"
        if not os.path.exists(fichier):
            return {"success": True, "stats": {"total": 0, "envoyees": 0, "entretiens": 0, "taux_reponse": 0}}
        with open(fichier, "r", encoding="utf-8") as f:
            candidatures = json.load(f)
        total = len(candidatures)
        envoyees = len([c for c in candidatures if c["statut"] in ["envoyée", "vue", "entretien", "refus", "acceptée"]])
        entretiens = len([c for c in candidatures if c["statut"] == "entretien"])
        taux = round((entretiens / envoyees * 100) if envoyees > 0 else 0, 1)
        return {"success": True, "stats": {"total": total, "envoyees": envoyees, "entretiens": entretiens, "taux_reponse": taux}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
