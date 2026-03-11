from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
import json
import os
import requests
import io
from datetime import datetime
import jwt  # PyJWT
from jwt import PyJWKClient

app = FastAPI(title="JobAlert IA", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── SÉCURITÉ SUPABASE ───
security = HTTPBearer()

SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")

# Client JWKS pour vérifier les tokens ES256 (nouveau système Supabase)
_jwks_client = None

def get_jwks_client():
    global _jwks_client
    if _jwks_client is None and SUPABASE_URL:
        jwks_url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url)
    return _jwks_client

def verifier_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials

    # Essai 1 : nouveau système ES256 via JWKS
    try:
        client = get_jwks_client()
        if client:
            signing_key = client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                audience="authenticated"
            )
            return payload
    except Exception:
        pass

    # Essai 2 : ancien système HS256 via JWT Secret
    if SUPABASE_JWT_SECRET:
        try:
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET.encode("utf-8"),
                algorithms=["HS256"],
                audience="authenticated"
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expiré — reconnecte-toi")
        except jwt.InvalidTokenError as e:
            raise HTTPException(status_code=401, detail=f"Token invalide : {str(e)}")

    raise HTTPException(status_code=401, detail="Impossible de vérifier le token")

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

# ─── HELPERS ───
def get_openai_client():
    from openai import OpenAI
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def get_access_token():
    url = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
    data = {
        "grant_type": "client_credentials",
        "client_id": os.environ["CLIENT_ID"],
        "client_secret": os.environ["CLIENT_SECRET"],
        "scope": "api_offresdemploiv2 o2dsoffre"
    }
    r = requests.post(url, params={"realm": "/partenaire"}, data=data, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]

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
    r = requests.get(url, headers=headers, params=params, timeout=15)
    r.raise_for_status()
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
    } for o in r.json().get("resultats", [])]

def scraper_tous_ats(mots_cles=""):
    offres = []
    for e in [
        {"nom": "Mistral AI", "slug": "mistral"},
        {"nom": "Qonto", "slug": "qonto"},
        {"nom": "Pennylane", "slug": "pennylane"},
        {"nom": "Swile", "slug": "swile"}
    ]:
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
                    "description": job.get("descriptionPlain", "")[:300],
                    "date_publication": datetime.utcfromtimestamp(job.get("createdAt", 0) / 1000).isoformat(),
                    "url": job.get("hostedUrl"),
                    "source": f"Lever ({e['nom']})",
                    "competences": []
                })
        except:
            pass

    for e in [
        {"nom": "Doctolib", "slug": "doctolib"},
        {"nom": "Alma", "slug": "alma"}
    ]:
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
                    "date_publication": job.get("updated_at", ""),
                    "url": job.get("absolute_url"),
                    "source": f"Greenhouse ({e['nom']})",
                    "competences": []
                })
        except:
            pass
    return offres

def analyser_cv(texte_cv):
    client = get_openai_client()
    prompt = f"""Analyse ce CV et extrais les informations en JSON :
{{"nom":"...","email":"...","competences":[],"secteurs":[],"annees_experience":0,"resume_profil":"..."}}
CV : {texte_cv}
Réponds UNIQUEMENT avec le JSON."""
    r = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], temperature=0.1)
    contenu = r.choices[0].message.content.strip()
    if "```" in contenu:
        contenu = contenu.split("```")[1]
        if contenu.startswith("json"):
            contenu = contenu[4:]
    return json.loads(contenu)

def scorer_compatibilite(profil, offre):
    client = get_openai_client()
    prompt = f"""Évalue la compatibilité en JSON :
{{"score":0,"points_forts":[],"points_faibles":[],"recommandation":""}}
PROFIL: {json.dumps(profil, ensure_ascii=False)}
OFFRE: Titre:{offre.get('titre')} Entreprise:{offre.get('entreprise')} Description:{offre.get('description','')[:400]}
Réponds UNIQUEMENT avec le JSON."""
    r = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], temperature=0.1)
    contenu = r.choices[0].message.content.strip()
    if "```" in contenu:
        contenu = contenu.split("```")[1]
        if contenu.startswith("json"):
            contenu = contenu[4:]
    return json.loads(contenu)

def adapter_cv(profil, offre, cv_original):
    client = get_openai_client()
    prompt = f"""Adapte ce CV pour cette offre.
OFFRE: {offre.get('titre')} chez {offre.get('entreprise')} - {offre.get('description','')[:300]}
CV: {cv_original}
Retourne le CV adapté directement."""
    r = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], temperature=0.3)
    return r.choices[0].message.content

def generer_lettre_motivation(profil, offre):
    client = get_openai_client()
    prompt = f"""Rédige une lettre de motivation (250-350 mots) pour ce poste.
Poste: {offre.get('titre')} chez {offre.get('entreprise')}
Description: {offre.get('description','')[:300]}
Profil: {profil.get('resume_profil','')}
Commence par une accroche mentionnant l'entreprise. Ton professionnel mais humain."""
    r = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], temperature=0.7)
    return r.choices[0].message.content

# ─── ROUTES PUBLIQUES ───
@app.get("/")
def root():
    return {"message": "JobAlert IA API — En ligne ✅"}

@app.post("/cv/extraire")
async def extraire_cv(file: UploadFile = File(...)):
    try:
        import pymupdf
        contenu = await file.read()
        doc = pymupdf.open(stream=contenu, filetype="pdf")
        texte = ""
        nb_pages = len(doc)
        for page in doc:
            texte += page.get_text()
        doc.close()
        if not texte.strip():
            raise HTTPException(status_code=400, detail="Le PDF ne contient pas de texte extractible")
        return {"success": True, "texte": texte.strip(), "pages": nb_pages}
    except ImportError:
        raise HTTPException(status_code=500, detail="pymupdf non installé")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/debug/token")
async def debug_token(request: Request):
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return {"erreur": "Pas de token Bearer", "header": auth[:50]}
    token = auth[7:]
    # Test ES256
    try:
        client = get_jwks_client()
        if client:
            signing_key = client.get_signing_key_from_jwt(token)
            payload = jwt.decode(token, signing_key.key, algorithms=["ES256", "RS256"], audience="authenticated")
            return {"statut": "OK ✅ (ES256)", "user_id": payload.get("sub")}
    except Exception as e1:
        # Test HS256
        try:
            payload = jwt.decode(token, SUPABASE_JWT_SECRET.encode("utf-8"), algorithms=["HS256"], audience="authenticated")
            return {"statut": "OK ✅ (HS256)", "user_id": payload.get("sub")}
        except Exception as e2:
            return {"statut": "ERREUR ❌", "ES256": str(e1), "HS256": str(e2), "token_debut": token[:40]}

# ─── ROUTES PROTÉGÉES ───

@app.post("/offres/france-travail")
def get_offres_ft(criteres: CriteresRecherche, user=Depends(verifier_token)):
    try:
        offres = rechercher_offres(criteres.dict())
        return {"success": True, "offres": offres, "total": len(offres)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/offres/ats")
def get_offres_ats(criteres: CriteresRecherche, user=Depends(verifier_token)):
    try:
        offres = scraper_tous_ats(mots_cles=criteres.motsCles)
        return {"success": True, "offres": offres, "total": len(offres)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/offres/toutes")
def get_toutes_offres(criteres: CriteresRecherche, user=Depends(verifier_token)):
    offres_ft = []
    offres_ats = []
    erreurs = []
    try:
        offres_ft = rechercher_offres(criteres.dict())
    except Exception as e:
        erreurs.append(f"France Travail : {str(e)}")
    try:
        offres_ats = scraper_tous_ats(mots_cles=criteres.motsCles)
    except Exception as e:
        erreurs.append(f"ATS : {str(e)}")
    toutes = offres_ft + offres_ats
    return {
        "success": True,
        "offres": toutes,
        "total": len(toutes),
        "sources": {"france_travail": len(offres_ft), "ats": len(offres_ats)},
        "erreurs": erreurs
    }

@app.post("/ia/analyser-cv")
def route_analyser_cv(demande: AnalyseCV, user=Depends(verifier_token)):
    try:
        return {"success": True, "profil": analyser_cv(demande.texte_cv)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ia/scorer")
def route_scorer(demande: DemandeScoring, user=Depends(verifier_token)):
    try:
        return {"success": True, "score": scorer_compatibilite(demande.profil, demande.offre)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ia/lettre")
def route_lettre(demande: DemandeLettre, user=Depends(verifier_token)):
    try:
        return {"success": True, "lettre": generer_lettre_motivation(demande.profil, demande.offre)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ia/package-complet")
def route_package_complet(demande: DemandeCV, user=Depends(verifier_token)):
    try:
        score = scorer_compatibilite(demande.profil, demande.offre)
        cv_adapte = adapter_cv(demande.profil, demande.offre, demande.cv_original)
        lettre = generer_lettre_motivation(demande.profil, demande.offre)
        return {"success": True, "score": score, "cv_adapte": cv_adapte, "lettre": lettre}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/candidatures/{user_id}")
def get_candidatures(user_id: str, user=Depends(verifier_token)):
    try:
        fichier = f"candidatures_{user_id}.json"
        if not os.path.exists(fichier):
            return {"success": True, "candidatures": []}
        with open(fichier, "r", encoding="utf-8") as f:
            return {"success": True, "candidatures": json.load(f)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats/{user_id}")
def get_stats(user_id: str, user=Depends(verifier_token)):
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
