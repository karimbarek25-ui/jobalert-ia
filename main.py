"""
API FastAPI — JobAlert IA
Point d'entrée principal
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import json
import os
import requests
from datetime import datetime
from openai import OpenAI

# ─── CONFIGURATION ───
CLIENT_ID = os.environ.get("CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "")
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY")) 

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

# ─── FRANCE TRAVAIL ───
def get_access_token():
    url = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
    params = {"realm": "/partenaire"}
    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "api_offresdemploiv2 o2dsoffre"
    }
    response = requests.post(url, params=params, data=data)
    response.raise_for_status()
    return response.json()["access_token"]

def rechercher_offres(criteres):
    token = get_access_token()
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {
        "motsCles": criteres.get("motsCles", ""),
        "range": f"0-{criteres.get('nbResultats', 10) - 1}",
        "sort": "1"
    }
    if criteres.get("typeContrat"):
        params["typeContrat"] = criteres["typeContrat"]

    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    data = response.json()
    offres = data.get("resultats", [])

    return [{
        "id": o.get("id"),
        "titre": o.get("intitule"),
        "entreprise": o.get("entreprise", {}).get("nom", "Non précisé"),
        "lieu": o.get("lieuTravail", {}).get("libelle"),
        "contrat": o.get("typeContratLibelle"),
        "salaire": o.get("salaire", {}).get("libelle", "Non précisé"),
        "description": o.get("description", ""),
        "date_publication": o.get("dateCreation"),
        "url": o.get("origineOffre", {}).get("urlOrigine", f"https://www.francetravail.fr/offres/emploi/offre/{o.get('id')}"),
        "source": "France Travail",
        "competences": [c.get("libelle") for c in o.get("competences", [])],
    } for o in offres]

# ─── ATS ───
ENTREPRISES_LEVER = [
    {"nom": "Mistral AI", "slug": "mistral"},
    {"nom": "Qonto", "slug": "qonto"},
    {"nom": "Pennylane", "slug": "pennylane"},
    {"nom": "Swile", "slug": "swile"},
]

ENTREPRISES_GREENHOUSE = [
    {"nom": "Doctolib", "slug": "doctolib"},
    {"nom": "Alma", "slug": "alma"},
]

def scraper_tous_ats(mots_cles=""):
    offres = []
    for e in ENTREPRISES_LEVER:
        try:
            r = requests.get(f"https://api.lever.co/v0/postings/{e['slug']}?mode=json", timeout=10)
            for job in r.json():
                if mots_cles and mots_cles.lower() not in job.get("text", "").lower():
                    continue
                offres.append({
                    "id": f"lever_{job.get('id')}",
                    "titre": job.get("text"),
                    "entreprise": e["nom"],
                    "lieu": job.get("categories", {}).get("location", "Non précisé"),
                    "contrat": job.get("categories", {}).get("commitment", "Non précisé"),
                    "salaire": "Non précisé",
                    "description": job.get("descriptionPlain", "")[:500],
                    "date_publication": datetime.utcfromtimestamp(job.get("createdAt", 0) / 1000).isoformat(),
                    "url": job.get("hostedUrl"),
                    "source": f"Lever ({e['nom']})",
                    "competences": [],
                })
        except: pass
    for e in ENTREPRISES_GREENHOUSE:
        try:
            r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{e['slug']}/jobs", timeout=10)
            for job in r.json().get("jobs", []):
                if mots_cles and mots_cles.lower() not in job.get("title", "").lower():
                    continue
                offres.append({
                    "id": f"greenhouse_{job.get('id')}",
                    "titre": job.get("title"),
                    "entreprise": e["nom"],
                    "lieu": job.get("location", {}).get("name", "Non précisé"),
                    "contrat": "Non précisé",
                    "salaire": "Non précisé",
                    "description": "",
                    "date_publication": job.get("updated_at", datetime.utcnow().isoformat()),
                    "url": job.get("absolute_url"),
                    "source": f"Greenhouse ({e['nom']})",
                    "competences": [],
                })
        except: pass
    return offres

# ─── IA ───
def analyser_cv(texte_cv):
    prompt = f"""Analyse ce CV et extrais les informations en JSON :
{{"nom":"...","email":"...","telephone":"...","competences":[],"experiences":[],"formations":[],"secteurs":[],"langues":[],"annees_experience":0,"pretention_salariale_min":0,"pretention_salariale_max":0,"localisation":"...","resume_profil":"..."}}
CV : {texte_cv}
Réponds UNIQUEMENT avec le JSON."""
    r = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":prompt}], temperature=0.1)
    contenu = r.choices[0].message.content.strip()
    if "```" in contenu:
        contenu = contenu.split("```")[1]
        if contenu.startswith("json"): contenu = contenu[4:]
    return json.loads(contenu)

def scorer_compatibilite(profil, offre):
    prompt = f"""Évalue la compatibilité entre ce candidat et cette offre en JSON :
{{"score":0,"points_forts":[],"points_faibles":[],"recommandation":"","mots_cles_manquants":[]}}
PROFIL: {json.dumps(profil, ensure_ascii=False)}
OFFRE: Titre:{offre.get('titre')} Entreprise:{offre.get('entreprise')} Description:{offre.get('description','')[:500]}
Réponds UNIQUEMENT avec le JSON."""
    r = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":prompt}], temperature=0.1)
    contenu = r.choices[0].message.content.strip()
    if "```" in contenu:
        contenu = contenu.split("```")[1]
        if contenu.startswith("json"): contenu = contenu[4:]
    return json.loads(contenu)

def adapter_cv(profil, offre, cv_original):
    prompt = f"""Adapte ce CV pour cette offre en mettant en avant les compétences pertinentes.
OFFRE: {offre.get('titre')} chez {offre.get('entreprise')} - {offre.get('description','')[:400]}
CV: {cv_original}
Retourne le CV adapté directement."""
    r = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":prompt}], temperature=0.3)
    return r.choices[0].message.content

def generer_lettre_motivation(profil, offre):
    prompt = f"""Rédige une lettre de motivation percutante pour ce poste (250-350 mots).
Poste: {offre.get('titre')} chez {offre.get('entreprise')}
Description: {offre.get('description','')[:400]}
Profil: {profil.get('resume_profil','')} - {', '.join(profil.get('competences',[])[:5])}
Commence par une accroche qui mentionne l'entreprise. Ton professionnel mais humain."""
    r = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":prompt}], temperature=0.7)
    return r.choices[0].message.content

# ─── ROUTES ───
@app.get("/")
def root():
    return {"message": "JobAlert IA API — En ligne ✅"}

@app.post("/offres/france-travail")
def get_offres_ft(criteres: CriteresRecherche):
    try:
        offres = rechercher_offres(criteres.dict())
        return {"success": True, "offres": offres, "total": len(offres)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/offres/ats")
def get_offres_ats(criteres: CriteresRecherche):
    try:
        offres = scraper_tous_ats(mots_cles=criteres.motsCles)
        return {"success": True, "offres": offres, "total": len(offres)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/offres/toutes")
def get_toutes_offres(criteres: CriteresRecherche):
    try:
        offres_ft = rechercher_offres(criteres.dict())
        offres_ats = scraper_tous_ats(mots_cles=criteres.motsCles)
        toutes = offres_ft + offres_ats
        return {"success": True, "offres": toutes, "total": len(toutes)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ia/analyser-cv")
def route_analyser_cv(demande: AnalyseCV):
    try:
        profil = analyser_cv(demande.texte_cv)
        return {"success": True, "profil": profil}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ia/scorer")
def route_scorer(demande: DemandeScoring):
    try:
        score = scorer_compatibilite(demande.profil, demande.offre)
        return {"success": True, "score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ia/lettre")
def route_lettre(demande: DemandeLettre):
    try:
        lettre = generer_lettre_motivation(demande.profil, demande.offre)
        return {"success": True, "lettre": lettre}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ia/package-complet")
def route_package_complet(demande: DemandeCV):
    try:
        score = scorer_compatibilite(demande.profil, demande.offre)
        cv_adapte = adapter_cv(demande.profil, demande.offre, demande.cv_original)
        lettre = generer_lettre_motivation(demande.profil, demande.offre)
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
            return {"success": True, "candidatures": json.load(f)}
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
        envoyees = len([c for c in candidatures if c["statut"] in ["envoyée","vue","entretien","refus","acceptée"]])
        entretiens = len([c for c in candidatures if c["statut"] == "entretien"])
        taux = round((entretiens / envoyees * 100) if envoyees > 0 else 0, 1)
        return {"success": True, "stats": {"total": total, "envoyees": envoyees, "entretiens": entretiens, "taux_reponse": taux}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
