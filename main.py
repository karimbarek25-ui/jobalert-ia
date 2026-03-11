from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
import json, os, requests, re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import jwt
from jwt import PyJWKClient

app = FastAPI(title="JobAlert IA", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

security = HTTPBearer()
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")

_jwks_client = None
def get_jwks_client():
    global _jwks_client
    if _jwks_client is None and SUPABASE_URL:
        _jwks_client = PyJWKClient(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json")
    return _jwks_client

def verifier_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        client = get_jwks_client()
        if client:
            signing_key = client.get_signing_key_from_jwt(token)
            payload = jwt.decode(token, signing_key.key, algorithms=["ES256", "RS256"], audience="authenticated")
            return payload
    except Exception:
        pass
    if SUPABASE_JWT_SECRET:
        try:
            payload = jwt.decode(token, SUPABASE_JWT_SECRET.encode("utf-8"), algorithms=["HS256"], audience="authenticated")
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expiré")
        except jwt.InvalidTokenError as e:
            raise HTTPException(status_code=401, detail=f"Token invalide : {str(e)}")
    raise HTTPException(status_code=401, detail="Impossible de vérifier le token")

# ─── MODÈLES ───
class CriteresRecherche(BaseModel):
    motsCles: str
    typeContrat: Optional[str] = ""
    localisation: Optional[str] = ""
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

class SauvegardeOffre(BaseModel):
    user_id: str
    offre: dict

class MajCandidature(BaseModel):
    user_id: str
    offre_id: str
    statut: str
    offre: Optional[dict] = None

class SauvegardeProfile(BaseModel):
    user_id: str
    profil: dict
    criteres: dict

class DemandeAdapterLettre(BaseModel):
    profil: dict
    offre: dict
    lm_base: str  # LM personnelle de l'utilisateur

class DemandeAdapterCV(BaseModel):
    profil: dict
    offre: dict
    cv_original: str  # texte brut original
    cv_base64: Optional[str] = None  # fichier PDF/DOCX original en base64

class DemandePackageComplet(BaseModel):
    profil: dict
    offre: dict
    cv_original: str
    lm_base: Optional[str] = None
    cv_base64: Optional[str] = None

class DemandeLMPDF(BaseModel):
    texte_lm: str
    titre_offre: Optional[str] = ""
    entreprise: Optional[str] = ""
    nom_candidat: Optional[str] = ""

# ─── HEADERS ───
H_BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}
H_JSON = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

# ─── UTILITAIRES ───
def get_openai_client():
    from openai import OpenAI
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def match(texte: str, mots: str) -> bool:
    if not mots:
        return True
    return any(m.lower() in texte.lower() for m in mots.split())

def offre(id, titre, entreprise, lieu, contrat, salaire, description, date, url, source, competences=None):
    return {
        "id": str(id), "titre": titre or "Non précisé", "entreprise": entreprise or "Non précisé",
        "lieu": lieu or "Non précisé", "contrat": contrat or "Non précisé",
        "salaire": salaire or "Non précisé", "description": (description or "")[:600],
        "date_publication": date or datetime.now().isoformat(),
        "url": url or "#", "source": source, "competences": competences or []
    }

def get_access_token():
    r = requests.post(
        "https://entreprise.francetravail.fr/connexion/oauth2/access_token",
        params={"realm": "/partenaire"},
        data={"grant_type": "client_credentials", "client_id": os.environ["CLIENT_ID"],
              "client_secret": os.environ["CLIENT_SECRET"], "scope": "api_offresdemploiv2 o2dsoffre"},
        timeout=10
    )
    r.raise_for_status()
    return r.json()["access_token"]

# ══════════════════════════════════════════════
# 🔵  FRANCE TRAVAIL
# ══════════════════════════════════════════════
def scraper_ft(criteres: dict):
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"motsCles": criteres.get("motsCles", ""), "range": f"0-{criteres.get('nbResultats', 20)-1}", "sort": "1"}
    if criteres.get("typeContrat"): params["typeContrat"] = criteres["typeContrat"]
    if criteres.get("localisation"): params["commune"] = criteres["localisation"]
    if criteres.get("distance"): params["distance"] = criteres["distance"]
    r = requests.get("https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search", headers=headers, params=params, timeout=15)
    r.raise_for_status()
    return [offre(
        o.get("id"), o.get("intitule"), o.get("entreprise", {}).get("nom"),
        o.get("lieuTravail", {}).get("libelle"), o.get("typeContratLibelle"),
        o.get("salaire", {}).get("libelle"), o.get("description"), o.get("dateCreation"),
        o.get("origineOffre", {}).get("urlOrigine", f"https://www.francetravail.fr/offres/emploi/offre/{o.get('id')}"),
        "France Travail", [c.get("libelle") for c in o.get("competences", [])]
    ) for o in r.json().get("resultats", [])]

# ══════════════════════════════════════════════
# 🟣  LEVER
# ══════════════════════════════════════════════
def scraper_lever(entreprises: list, mots: str = ""):
    result = []
    for e in entreprises:
        try:
            r = requests.get(f"https://api.lever.co/v0/postings/{e['slug']}?mode=json", timeout=8, headers=H_JSON)
            for j in r.json():
                if not match(j.get("text","") + j.get("descriptionPlain",""), mots): continue
                result.append(offre(
                    f"lever_{j.get('id')}", j.get("text"), e["nom"],
                    j.get("categories",{}).get("location"), j.get("categories",{}).get("commitment"),
                    None, j.get("descriptionPlain",""),
                    datetime.utcfromtimestamp(j.get("createdAt",0)/1000).isoformat(),
                    j.get("hostedUrl"), f"Site carrière ({e['nom']})"
                ))
        except: pass
    return result

# ══════════════════════════════════════════════
# 🟢  GREENHOUSE
# ══════════════════════════════════════════════
def scraper_greenhouse(entreprises: list, mots: str = ""):
    result = []
    for e in entreprises:
        try:
            r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{e['slug']}/jobs", timeout=8, headers=H_JSON)
            for j in r.json().get("jobs", []):
                if not match(j.get("title",""), mots): continue
                result.append(offre(
                    f"gh_{j.get('id')}", j.get("title"), e["nom"],
                    j.get("location",{}).get("name"), None, None, None,
                    j.get("updated_at"), j.get("absolute_url"), f"Site carrière ({e['nom']})"
                ))
        except: pass
    return result

# ══════════════════════════════════════════════
# 🟡  WELCOME TO THE JUNGLE
# ══════════════════════════════════════════════
def scraper_wttj(mots: str = "", localisation: str = ""):
    result = []
    try:
        params = {"query": mots, "page": 1, "per_page": 20}
        if localisation: params["aroundQuery"] = localisation
        r = requests.get("https://api.welcometothejungle.com/api/v1/jobs", params=params, headers=H_JSON, timeout=10)
        if r.status_code == 200:
            for j in r.json().get("jobs", []):
                result.append(offre(
                    f"wttj_{j.get('slug', j.get('id'))}", j.get("name"),
                    j.get("organization",{}).get("name"), j.get("office",{}).get("city"),
                    j.get("contract_type",{}).get("name"), None, j.get("description",""),
                    j.get("published_at"),
                    f"https://www.welcometothejungle.com/jobs/{j.get('slug')}",
                    "Welcome to the Jungle", [s.get("name") for s in j.get("skills",[])]
                ))
    except: pass
    return result

# ══════════════════════════════════════════════
# 🔴  SMARTRECRUITERS (API publique gratuite)
# Slugs vérifiés sur careers.smartrecruiters.com
# ══════════════════════════════════════════════
def scraper_smartrecruiters(entreprises: list, mots: str = ""):
    result = []
    for e in entreprises:
        try:
            params = {"limit": 20, "offset": 0}
            if mots: params["q"] = mots
            r = requests.get(
                f"https://api.smartrecruiters.com/v1/companies/{e['slug']}/postings",
                params=params, headers=H_JSON, timeout=10
            )
            if r.status_code == 200:
                for j in r.json().get("content", []):
                    titre = j.get("name","")
                    if not match(titre, mots): continue
                    loc = j.get("location",{})
                    lieu = ", ".join(filter(None, [loc.get("city"), loc.get("country")]))
                    result.append(offre(
                        f"sr_{j.get('id')}", titre, e["nom"],
                        lieu or "Non précisé",
                        j.get("typeOfEmployment",{}).get("label"),
                        None, None, j.get("releasedDate"),
                        f"https://jobs.smartrecruiters.com/{e['slug']}/{j.get('id')}",
                        f"Site carrière ({e['nom']})"
                    ))
        except: pass
    return result

# ══════════════════════════════════════════════
# 🟠  WORKDAY (API JSON publique)
# Tenants vérifiés sur *.myworkdayjobs.com
# ══════════════════════════════════════════════
def scraper_workday_one(e: dict, mots: str = ""):
    result = []
    try:
        # L'API Workday CXS est publique et retourne du JSON
        url = f"https://{e['tenant']}.wd3.myworkdayjobs.com/wday/cxs/{e['tenant']}/{e['path']}/jobs"
        payload = {"limit": 20, "offset": 0, "searchText": mots or ""}
        r = requests.post(url, json=payload, headers={**H_JSON, "Content-Type": "application/json"}, timeout=12)
        if r.status_code == 200:
            for j in r.json().get("jobPostings", []):
                titre = j.get("title","")
                if not match(titre, mots): continue
                external_path = j.get("externalPath","")
                result.append(offre(
                    f"wd_{e['nom'].replace(' ','_')}_{external_path.replace('/','_')}",
                    titre, e["nom"],
                    j.get("locationsText","Non précisé"),
                    None, None, None, j.get("postedOn"),
                    f"https://{e['tenant']}.wd3.myworkdayjobs.com{external_path}",
                    f"Site carrière ({e['nom']})"
                ))
    except: pass
    return result

def scraper_workday(entreprises: list, mots: str = ""):
    result = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(scraper_workday_one, e, mots): e for e in entreprises}
        for f in as_completed(futures):
            try: result.extend(f.result())
            except: pass
    return result

# ══════════════════════════════════════════════
# 🔵  TALEO / ORACLE (portail propre HTML)
# ══════════════════════════════════════════════
def scraper_taleo_one(e: dict, mots: str = ""):
    result = []
    try:
        url = f"https://sjobs.brassring.com/TGnewUI/Search/home/HomeWithPreLoad?partnerid={e['partner']}&siteid={e['site']}&type=search&JobReq={mots}"
        r = requests.get(url, headers=H_BROWSER, timeout=12)
        # Extraction simplifiée via regex des titres
        titres = re.findall(r'class="jobTitle"[^>]*>([^<]+)<', r.text)
        liens = re.findall(r'href="([^"]*JobReqDetail[^"]*)"', r.text)
        for i, titre in enumerate(titres[:20]):
            if not match(titre, mots): continue
            lien = liens[i] if i < len(liens) else e.get("base_url","#")
            result.append(offre(
                f"taleo_{e['nom']}_{i}", titre.strip(), e["nom"],
                e.get("pays","France"), None, None, None, None, lien,
                f"Site carrière ({e['nom']})"
            ))
    except: pass
    return result

# ══════════════════════════════════════════════
# 🟤  PORTAILS HTML PROPRES
# Pour les entreprises sans ATS standard
# ══════════════════════════════════════════════
def scraper_html_one(e: dict, mots: str = ""):
    """Scraper générique pour portails HTML avec BeautifulSoup"""
    result = []
    try:
        from bs4 import BeautifulSoup
        r = requests.get(e["url"], headers=H_BROWSER, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        # Cherche les balises les plus communes pour les listes d'offres
        selectors = e.get("selectors", ["h2", "h3", ".job-title", ".offer-title", ".position-title", "td a"])
        titres_trouves = []
        for sel in selectors:
            titres_trouves = soup.select(sel)
            if titres_trouves: break
        for i, el in enumerate(titres_trouves[:20]):
            titre = el.get_text(strip=True)
            if not titre or len(titre) < 5: continue
            if not match(titre, mots): continue
            lien = el.get("href") or (el.find("a") and el.find("a").get("href")) or e["url"]
            if lien and not lien.startswith("http"): lien = e.get("base_url","") + lien
            result.append(offre(
                f"html_{e['nom'].replace(' ','_')}_{i}", titre, e["nom"],
                e.get("lieu","France"), None, None, None, None,
                lien or e["url"], f"Site carrière ({e['nom']})"
            ))
    except: pass
    return result

def scraper_html(entreprises: list, mots: str = ""):
    result = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(scraper_html_one, e, mots): e for e in entreprises}
        for f in as_completed(futures):
            try: result.extend(f.result())
            except: pass
    return result

# ══════════════════════════════════════════════
# 📋  LISTE COMPLÈTE DES ENTREPRISES PAR ATS
# ══════════════════════════════════════════════

# ── LEVER (API publique gratuite) ──
LEVER_ENTREPRISES = [
    # Tech / FinTech
    {"nom": "Mistral AI", "slug": "mistral"},
    {"nom": "Qonto", "slug": "qonto"},
    {"nom": "Pennylane", "slug": "pennylane"},
    {"nom": "Swile", "slug": "swile"},
    {"nom": "Contentsquare", "slug": "contentsquare"},
    {"nom": "Dataiku", "slug": "dataiku"},
    {"nom": "PayFit", "slug": "payfit"},
    {"nom": "Alan", "slug": "alan"},
    {"nom": "Spendesk", "slug": "spendesk"},
    {"nom": "Aircall", "slug": "aircall"},
    {"nom": "Ankorstore", "slug": "ankorstore"},
    # RH / Conseil
    {"nom": "Randstad Digital", "slug": "randstaddigital"},
    # Marketing
    {"nom": "Ogury", "slug": "ogury"},
]

# ── GREENHOUSE (API publique gratuite) ──
GREENHOUSE_ENTREPRISES = [
    # Santé / Insurtech
    {"nom": "Doctolib", "slug": "doctolib"},
    {"nom": "Alma", "slug": "alma"},
    # E-commerce / Marketplace
    {"nom": "Back Market", "slug": "backmarket"},
    {"nom": "Vestiaire Collective", "slug": "vestiairecollective"},
    {"nom": "ManoMano", "slug": "manomano"},
    {"nom": "Leboncoin", "slug": "adevintafrance"},
    # Transport / Mobilité
    {"nom": "BlaBlaCar", "slug": "blablacar"},
    # Finance / Crypto
    {"nom": "Ledger", "slug": "ledger"},
    {"nom": "Lydia", "slug": "lydia"},
    {"nom": "Younited", "slug": "younited"},
    # Conseil / ESN
    {"nom": "Capgemini", "slug": "capgemini"},
    {"nom": "Sopra Steria", "slug": "soprasteria"},
]

# ── SMARTRECRUITERS (API publique gratuite) ──
# Slugs vérifiés sur careers.smartrecruiters.com/<slug>
SMARTRECRUITERS_ENTREPRISES = [
    # Distribution / Retail
    {"nom": "Decathlon", "slug": "DECATHLON"},
    {"nom": "Leroy Merlin", "slug": "LeroyMerlinFrance"},
    {"nom": "Carrefour", "slug": "Carrefour"},
    {"nom": "Fnac Darty", "slug": "FnacDarty"},
    {"nom": "Cdiscount", "slug": "Cdiscount"},
    # Luxe / Mode / Beauté
    {"nom": "LVMH Perfumes & Cosmetics", "slug": "LVMHPerfumesCosmetics"},
    {"nom": "Kering", "slug": "Kering"},
    {"nom": "Sephora", "slug": "Sephora"},
    # Finance / Banque / Assurance
    {"nom": "BNP Paribas", "slug": "BNPParibas"},
    {"nom": "AXA", "slug": "AXA"},
    {"nom": "Société Générale", "slug": "SocieteGenerale"},
    {"nom": "Crédit Agricole", "slug": "CreditAgricole"},
    # Energie / Industrie
    {"nom": "Engie", "slug": "ENGIE"},
    {"nom": "Veolia", "slug": "Veolia"},
    # BTP / Construction
    {"nom": "Vinci", "slug": "Vinci"},
    {"nom": "Bouygues", "slug": "Bouygues"},
    {"nom": "Saint-Gobain", "slug": "SaintGobain"},
    # Télécoms
    {"nom": "Orange", "slug": "Orange"},
    {"nom": "SFR", "slug": "SFR"},
    # Conseil / Audit
    {"nom": "Accenture", "slug": "Accenture"},
    {"nom": "Deloitte France", "slug": "DeloitteFrance"},
    {"nom": "PwC France", "slug": "PwCFrance"},
    # Agroalimentaire
    {"nom": "Danone", "slug": "Danone"},
    {"nom": "Pernod Ricard", "slug": "PernodRicard"},
    # RH / Interim
    {"nom": "Adecco", "slug": "Adecco"},
    {"nom": "Manpower", "slug": "ManpowerGroup"},
    # Santé / Pharma
    {"nom": "Sanofi", "slug": "Sanofi"},
    {"nom": "Ipsen", "slug": "Ipsen"},
    # Transport / Logistique
    {"nom": "XPO Logistics", "slug": "XPOLogistics"},
    {"nom": "Geodis", "slug": "Geodis"},
    # Immobilier
    {"nom": "Nexity", "slug": "Nexity"},
    {"nom": "Icade", "slug": "Icade"},
    # Hôtellerie / Restauration
    {"nom": "Sodexo", "slug": "Sodexo"},
    {"nom": "Compass Group", "slug": "CompassGroup"},
    # Tech / ESN
    {"nom": "Thales", "slug": "Thales"},
    {"nom": "Atos", "slug": "Atos"},
]

# ── WORKDAY (API JSON publique — tenant + path vérifiés) ──
WORKDAY_ENTREPRISES = [
    # Beauté / Cosmétique
    {"nom": "L'Oréal", "tenant": "loreal", "path": "Careers"},
    # Industrie / Aéronautique
    {"nom": "Airbus", "tenant": "airbus", "path": "Airbus"},
    {"nom": "Schneider Electric", "tenant": "schneider", "path": "Schneider_Electric_Careers"},
    {"nom": "Safran", "tenant": "safran", "path": "Safran"},
    {"nom": "Michelin", "tenant": "michelin", "path": "Michelin_Jobs"},
    # Energie
    {"nom": "TotalEnergies", "tenant": "totalenergies", "path": "TotalEnergies"},
    {"nom": "EDF", "tenant": "edf", "path": "EDF"},
    # Luxe
    {"nom": "Hermès", "tenant": "hermes", "path": "Hermes"},
    # Hôtellerie
    {"nom": "Accor", "tenant": "accor", "path": "Accor_Careers"},
    # Automobile
    {"nom": "Renault", "tenant": "renault", "path": "Renault_Group"},
    {"nom": "Stellantis", "tenant": "stellantis", "path": "Stellantis"},
    # Distribution
    {"nom": "Auchan", "tenant": "auchan", "path": "Auchan_Careers"},
    # Conseil / IT
    {"nom": "Publicis", "tenant": "publicis", "path": "Publicis_Groupe"},
    {"nom": "Dassault Systèmes", "tenant": "dassault", "path": "DassaultSystemes"},
    # Finance
    {"nom": "Amundi", "tenant": "amundi", "path": "Amundi"},
]

# ── PORTAILS HTML PROPRES ──
# Pour les entreprises sans ATS standard ou avec portail maison
HTML_ENTREPRISES = [
    {
        "nom": "Intermarché / Les Mousquetaires",
        "url": "https://recrutement.mousquetaires.com/nos-offres/",
        "base_url": "https://recrutement.mousquetaires.com",
        "selectors": [".job-title", "h3 a", ".offer__title"],
        "lieu": "France"
    },
    {
        "nom": "E.Leclerc",
        "url": "https://www.e-leclerc.com/recrutement",
        "base_url": "https://www.e-leclerc.com",
        "selectors": [".job-title", "h3 a"],
        "lieu": "France"
    },
    {
        "nom": "Lidl France",
        "url": "https://careers.lidl.fr/fr/offres-d-emploi",
        "base_url": "https://careers.lidl.fr",
        "selectors": [".job-title", "h3", ".vacancy-title"],
        "lieu": "France"
    },
    {
        "nom": "Aldi France",
        "url": "https://recrutement.aldi.fr/offres-d-emploi",
        "base_url": "https://recrutement.aldi.fr",
        "selectors": [".job-title", "h2", ".offer-title"],
        "lieu": "France"
    },
    {
        "nom": "SNCF",
        "url": "https://www.sncf.com/fr/recrutement/offres-emploi",
        "base_url": "https://www.sncf.com",
        "selectors": [".offer-title", "h3 a", ".job-item__title"],
        "lieu": "France"
    },
    {
        "nom": "Air France",
        "url": "https://recrutement.airfranceklm.com/nos-offres",
        "base_url": "https://recrutement.airfranceklm.com",
        "selectors": [".vacancy-title", "h3", ".job-title"],
        "lieu": "France"
    },
    {
        "nom": "La Poste",
        "url": "https://recrutement.laposte.fr/nos-offres-d-emploi",
        "base_url": "https://recrutement.laposte.fr",
        "selectors": [".offer__title", "h3 a", ".job-title"],
        "lieu": "France"
    },
    {
        "nom": "Crédit Mutuel",
        "url": "https://www.creditmutuel.fr/fr/vous/rejoignez-nous/nos-offres.html",
        "base_url": "https://www.creditmutuel.fr",
        "selectors": ["h3 a", ".offer-title", "td a"],
        "lieu": "France"
    },
    {
        "nom": "Havas",
        "url": "https://havas.com/fr/carrieres/nos-offres-demploi/",
        "base_url": "https://havas.com",
        "selectors": [".job-title", "h3 a", ".career-item__title"],
        "lieu": "France"
    },
    {
        "nom": "Chronopost / DPD",
        "url": "https://www.dpd.com/fr/fr/carrieres/offres-d-emploi/",
        "base_url": "https://www.dpd.com",
        "selectors": [".job-title", "h3 a"],
        "lieu": "France"
    },
    {
        "nom": "Boursorama Banque",
        "url": "https://recrutement.boursobank.com/offres",
        "base_url": "https://recrutement.boursobank.com",
        "selectors": [".offer-title", "h3", ".job-title"],
        "lieu": "France"
    },
    {
        "nom": "Leclerc / CDM",
        "url": "https://www.mouvement-leclerc.com/recrutement/offres-emploi",
        "base_url": "https://www.mouvement-leclerc.com",
        "selectors": ["h3 a", ".job-offer__title"],
        "lieu": "France"
    },
]

# ══════════════════════════════════════════════
# 🚀  SCRAPER PRINCIPAL (parallélisé)
# ══════════════════════════════════════════════
def scraper_tous(mots: str = "", localisation: str = ""):
    """Lance tous les scrapers en parallèle et agrège les résultats"""
    toutes = []
    erreurs = []

    scrapers = [
        ("Lever", lambda: scraper_lever(LEVER_ENTREPRISES, mots)),
        ("Greenhouse", lambda: scraper_greenhouse(GREENHOUSE_ENTREPRISES, mots)),
        ("SmartRecruiters", lambda: scraper_smartrecruiters(SMARTRECRUITERS_ENTREPRISES, mots)),
        ("Workday", lambda: scraper_workday(WORKDAY_ENTREPRISES, mots)),
        ("Welcome to the Jungle", lambda: scraper_wttj(mots, localisation)),
        ("Portails HTML", lambda: scraper_html(HTML_ENTREPRISES, mots)),
    ]

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(fn): nom for nom, fn in scrapers}
        for future in as_completed(futures):
            nom = futures[future]
            try:
                res = future.result(timeout=20)
                toutes.extend(res)
            except Exception as e:
                erreurs.append(f"{nom}: {str(e)}")

    # Dédoublonnage par titre + entreprise
    seen = set()
    dedup = []
    for o in toutes:
        key = (o["titre"].lower().strip(), o["entreprise"].lower().strip())
        if key not in seen:
            seen.add(key)
            dedup.append(o)

    return dedup, erreurs

# ══════════════════════════════════════════════
# 🤖  IA
# ══════════════════════════════════════════════
def analyser_cv(texte: str):
    client = get_openai_client()
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"""Analyse ce CV et retourne uniquement un JSON strict :
{{"nom":"","email":"","telephone":"","competences":[],"secteurs":[],"annees_experience":0,"dernier_poste":"","formation":"","langues":[],"resume_profil":""}}
CV: {texte[:4000]}"""}],
        temperature=0.1, response_format={"type": "json_object"}
    )
    return json.loads(r.choices[0].message.content)

def scorer(profil: dict, o: dict):
    client = get_openai_client()
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"""Tu es un expert RH. Évalue la compatibilité entre ce profil et cette offre. Réponds UNIQUEMENT en JSON strict :
{{"score":75,"points_forts":["raison 1","raison 2"],"points_faibles":["manque 1"],"recommandation":"conseil court"}}
PROFIL: {profil.get('nom','')} | Compétences: {', '.join(profil.get('competences',[])[:10])} | {profil.get('annees_experience',0)} ans | {profil.get('dernier_poste','')} | {profil.get('resume_profil','')[:200]}
OFFRE: {o.get('titre','')} chez {o.get('entreprise','')} | {o.get('lieu','')} | {o.get('contrat','')} | {o.get('description','')[:400]}"""}],
        temperature=0.1, response_format={"type": "json_object"}
    )
    return json.loads(r.choices[0].message.content)

def adapter_cv(profil: dict, o: dict, cv: str):
    """Adapte le texte du CV à l'offre en conservant la structure originale"""
    client = get_openai_client()
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"""Tu es expert RH. Adapte ce CV pour maximiser les chances pour ce poste.
RÈGLES STRICTES :
- Conserve EXACTEMENT la même structure, mise en forme et sections du CV original
- Réordonne les compétences pour mettre en avant celles qui correspondent à l'offre
- Reformule légèrement les expériences pour coller aux mots-clés de l'offre
- N'invente aucune expérience, diplôme ou compétence
- Retourne uniquement le CV adapté, sans commentaire

POSTE : {o.get('titre')} chez {o.get('entreprise')}
DESCRIPTION : {o.get('description','')[:500]}

CV ORIGINAL :
{cv[:3500]}"""}],
        temperature=0.2
    )
    return r.choices[0].message.content

def adapter_lettre(profil: dict, o: dict, lm_base: str):
    """Adapte la LM personnelle de l'utilisateur à l'offre spécifique"""
    client = get_openai_client()
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"""Tu es expert RH. Adapte cette lettre de motivation personnelle pour ce poste précis.
RÈGLES STRICTES :
- Conserve le style, le ton et la voix de l'auteur (ne la réécris pas de zéro)
- Remplace les références génériques par des éléments spécifiques à l'entreprise et au poste
- Intègre naturellement les mots-clés de l'offre
- Garde la même longueur approximative
- Renforce l'accroche en mentionnant l'entreprise par son nom
- Retourne uniquement la lettre adaptée, sans commentaire ni titre

POSTE : {o.get('titre')} chez {o.get('entreprise')}
DESCRIPTION OFFRE : {o.get('description','')[:400]}
PROFIL : {profil.get('resume_profil','')} — {profil.get('annees_experience',0)} ans exp.

LETTRE DE BASE DE L'UTILISATEUR :
{lm_base[:2500]}"""}],
        temperature=0.4
    )
    return r.choices[0].message.content

def generer_lettre(profil: dict, o: dict):
    """Génère une LM depuis zéro si l'utilisateur n'en a pas fourni"""
    client = get_openai_client()
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"""Rédige une lettre de motivation percutante (300-400 mots) pour ce poste.
Poste: {o.get('titre')} chez {o.get('entreprise')}
Description: {o.get('description','')[:400]}
Profil: {profil.get('resume_profil','')} — {profil.get('annees_experience',0)} ans — {', '.join(profil.get('competences',[])[:6])}
Commence par une accroche forte mentionnant l'entreprise. Retourne uniquement la lettre."""}],
        temperature=0.7
    )
    return r.choices[0].message.content

def generer_pdf_lm(texte_lm: str, titre_offre: str = "", entreprise: str = "", nom_candidat: str = "") -> bytes:
    """Génère un PDF propre de la lettre de motivation"""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4

    # Marges
    mx, my = 70, 70
    largeur = 595 - mx * 2

    # En-tête
    y = my
    if nom_candidat:
        page.insert_text((mx, y), nom_candidat, fontsize=13, fontname="helv", color=(0.1, 0.1, 0.4))
        y += 22
    if entreprise or titre_offre:
        label = f"Candidature : {titre_offre}" + (f" — {entreprise}" if entreprise else "")
        page.insert_text((mx, y), label, fontsize=10, fontname="helv", color=(0.4, 0.4, 0.4))
        y += 16
    # Date
    from datetime import date
    page.insert_text((mx, y), f"Le {date.today().strftime('%d/%m/%Y')}", fontsize=10, fontname="helv", color=(0.4,0.4,0.4))
    y += 30

    # Ligne séparatrice
    page.draw_line((mx, y), (595 - mx, y), color=(0.8, 0.8, 0.8), width=0.5)
    y += 20

    # Corps de la lettre
    for paragraphe in texte_lm.split("\n"):
        if not paragraphe.strip():
            y += 10
            continue
        # Découpage manuel des lignes longues
        mots = paragraphe.split(" ")
        ligne = ""
        for mot in mots:
            test = ligne + (" " if ligne else "") + mot
            # ~90 caractères par ligne en helv 11
            if len(test) > 90:
                page.insert_text((mx, y), ligne, fontsize=11, fontname="helv", color=(0,0,0))
                y += 16
                ligne = mot
                if y > 800:  # nouvelle page si débordement
                    page = doc.new_page(width=595, height=842)
                    y = my
            else:
                ligne = test
        if ligne:
            page.insert_text((mx, y), ligne, fontsize=11, fontname="helv", color=(0,0,0))
            y += 16
        if y > 800:
            page = doc.new_page(width=595, height=842)
            y = my

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes

def adapter_pdf_cv(cv_base64: str, texte_adapte: str) -> bytes:
    """Réinjecte le texte adapté dans le PDF original en conservant la mise en page"""
    import pymupdf, base64
    cv_bytes = base64.b64decode(cv_base64)
    doc_original = pymupdf.open(stream=cv_bytes, filetype="pdf")
    doc_adapte = pymupdf.open()

    # Stratégie : conserver les images/formes du PDF original, remplacer les blocs texte
    texte_paragraphes = [p.strip() for p in texte_adapte.split("\n") if p.strip()]
    para_idx = 0

    for page_orig in doc_original:
        page_new = doc_adapte.new_page(width=page_orig.rect.width, height=page_orig.rect.height)
        # Copier le contenu visuel (images, formes, couleurs)
        page_new.show_pdf_page(page_orig.rect, doc_original, page_orig.number)

        # Récupérer les blocs texte originaux pour les positions
        blocs = page_orig.get_text("blocks")
        for bloc in blocs:
            x0, y0, x1, y1, texte_bloc, block_no, block_type = bloc
            if block_type != 0:  # 0 = texte
                continue
            if not texte_bloc.strip():
                continue
            if para_idx < len(texte_paragraphes):
                # Couvrir l'ancien texte avec un rectangle blanc
                page_new.draw_rect(pymupdf.Rect(x0-2, y0-2, x1+2, y1+2), color=(1,1,1), fill=(1,1,1))
                # Insérer le nouveau texte à la même position
                page_new.insert_textbox(
                    pymupdf.Rect(x0, y0, x1, y1+50),
                    texte_paragraphes[para_idx],
                    fontsize=10, fontname="helv", color=(0,0,0)
                )
                para_idx += 1

    pdf_bytes = doc_adapte.tobytes()
    doc_adapte.close()
    doc_original.close()
    return pdf_bytes

# ── Données utilisateur ──
def charger_user(user_id):
    f = f"data_{user_id}.json"
    if os.path.exists(f):
        with open(f, "r", encoding="utf-8") as fp:
            return json.load(fp)
    return {"profil": {}, "criteres": {}, "favoris": [], "candidatures": []}

def sauver_user(user_id, data):
    with open(f"data_{user_id}.json", "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)

# ══════════════════════════════════════════════
# 🌐  ROUTES API
# ══════════════════════════════════════════════

@app.get("/")
def root():
    return {"message": "JobAlert IA API v3 — En ligne ✅", "sources": ["France Travail", "Lever", "Greenhouse", "SmartRecruiters", "Workday", "Welcome to the Jungle", "Portails HTML"]}

@app.get("/debug/token")
async def debug_token(request: Request):
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "): return {"erreur": "Pas de token"}
    token = auth[7:]
    try:
        client = get_jwks_client()
        if client:
            sk = client.get_signing_key_from_jwt(token)
            p = jwt.decode(token, sk.key, algorithms=["ES256","RS256"], audience="authenticated")
            return {"statut": "OK ✅ (ES256)", "user_id": p.get("sub")}
    except Exception as e1:
        try:
            p = jwt.decode(token, SUPABASE_JWT_SECRET.encode("utf-8"), algorithms=["HS256"], audience="authenticated")
            return {"statut": "OK ✅ (HS256)", "user_id": p.get("sub")}
        except Exception as e2:
            return {"statut": "ERREUR ❌", "ES256": str(e1), "HS256": str(e2)}

@app.post("/cv/extraire")
async def extraire_cv(file: UploadFile = File(...)):
    try:
        import pymupdf
        contenu = await file.read()
        doc = pymupdf.open(stream=contenu, filetype="pdf")
        texte = "".join(p.get_text() for p in doc)
        nb = len(doc)
        doc.close()
        if not texte.strip(): raise HTTPException(400, "PDF sans texte")
        return {"success": True, "texte": texte.strip(), "pages": nb}
    except ImportError:
        raise HTTPException(500, "pymupdf non installé")
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/offres/toutes")
def get_offres(criteres: CriteresRecherche, user=Depends(verifier_token)):
    offres_ft, erreurs_ft = [], []
    try:
        offres_ft = scraper_ft(criteres.dict())
    except Exception as e:
        erreurs_ft = [f"France Travail: {str(e)}"]

    offres_ats, erreurs_ats = scraper_tous(
        mots=criteres.motsCles,
        localisation=criteres.localisation or ""
    )

    toutes = offres_ft + offres_ats
    sources = {}
    for o in toutes:
        src = o.get("source","Autre")
        sources[src] = sources.get(src, 0) + 1

    return {
        "success": True,
        "offres": toutes,
        "total": len(toutes),
        "sources": sources,
        "erreurs": erreurs_ft + erreurs_ats
    }

@app.post("/ia/analyser-cv")
def route_analyser_cv(demande: AnalyseCV, user=Depends(verifier_token)):
    try:
        return {"success": True, "profil": analyser_cv(demande.texte_cv)}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/ia/scorer")
def route_scorer(demande: DemandeScoring, user=Depends(verifier_token)):
    try:
        return {"success": True, "score": scorer(demande.profil, demande.offre)}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/ia/scorer-batch")
def route_scorer_batch(req: dict, user=Depends(verifier_token)):
    try:
        profil = req.get("profil", {})
        offres = req.get("offres", [])
        resultats = []
        for o in offres[:10]:
            try:
                s = scorer(profil, o)
                resultats.append({"id": o.get("id"), "score": s})
            except:
                resultats.append({"id": o.get("id"), "score": {"score": 65, "points_forts": [], "points_faibles": [], "recommandation": ""}})
        return {"success": True, "resultats": resultats}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/ia/lettre")
def route_lettre(demande: DemandeLettre, user=Depends(verifier_token)):
    try:
        return {"success": True, "lettre": generer_lettre(demande.profil, demande.offre)}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/ia/adapter-lettre")
def route_adapter_lettre(demande: DemandeAdapterLettre, user=Depends(verifier_token)):
    """Adapte la LM personnelle de l'utilisateur à l'offre"""
    try:
        lm_adaptee = adapter_lettre(demande.profil, demande.offre, demande.lm_base)
        return {"success": True, "lettre": lm_adaptee}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/ia/adapter-cv")
def route_adapter_cv(demande: DemandeAdapterCV, user=Depends(verifier_token)):
    """Adapte le texte du CV à l'offre"""
    try:
        cv_adapte = adapter_cv(demande.profil, demande.offre, demande.cv_original)
        return {"success": True, "cv_adapte": cv_adapte}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/ia/package-complet")
def route_package(demande: DemandePackageComplet, user=Depends(verifier_token)):
    """Score + CV adapté + LM (depuis base perso ou générée)"""
    try:
        s = scorer(demande.profil, demande.offre)
        cv = adapter_cv(demande.profil, demande.offre, demande.cv_original)
        if demande.lm_base and demande.lm_base.strip():
            lettre = adapter_lettre(demande.profil, demande.offre, demande.lm_base)
        else:
            lettre = generer_lettre(demande.profil, demande.offre)
        return {"success": True, "score": s, "cv_adapte": cv, "lettre": lettre}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/cv/adapter-pdf")
async def route_adapter_pdf(request: Request, user=Depends(verifier_token)):
    """Réinjecte le texte CV adapté dans le PDF original — conserve la mise en page"""
    try:
        body = await request.json()
        cv_base64 = body.get("cv_base64")
        texte_adapte = body.get("texte_adapte", "")
        if not cv_base64:
            raise HTTPException(400, "cv_base64 manquant")
        pdf_bytes = adapter_pdf_cv(cv_base64, texte_adapte)
        from fastapi.responses import Response
        return Response(content=pdf_bytes, media_type="application/pdf",
                        headers={"Content-Disposition": "attachment; filename=cv_adapte.pdf"})
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/ia/lettre-pdf")
async def route_lettre_pdf(demande: DemandeLMPDF, user=Depends(verifier_token)):
    """Génère un PDF propre depuis le texte de la LM (éventuellement modifié par l'utilisateur)"""
    try:
        pdf_bytes = generer_pdf_lm(
            demande.texte_lm,
            demande.titre_offre,
            demande.entreprise,
            demande.nom_candidat
        )
        from fastapi.responses import Response
        return Response(content=pdf_bytes, media_type="application/pdf",
                        headers={"Content-Disposition": "attachment; filename=lettre_motivation.pdf"})
    except Exception as e:
        raise HTTPException(500, str(e))

# ── Profil ──
@app.post("/user/sauvegarder")
def sauvegarder_profil(req: SauvegardeProfile, user=Depends(verifier_token)):
    try:
        data = charger_user(req.user_id)
        data["profil"] = req.profil
        data["criteres"] = req.criteres
        sauver_user(req.user_id, data)
        return {"success": True}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/user/{user_id}")
def charger_profil(user_id: str, user=Depends(verifier_token)):
    try:
        return {"success": True, "data": charger_user(user_id)}
    except Exception as e:
        raise HTTPException(500, str(e))

# ── Favoris ──
@app.post("/favoris/ajouter")
def ajouter_favori(req: SauvegardeOffre, user=Depends(verifier_token)):
    try:
        data = charger_user(req.user_id)
        if not any(f.get("id") == req.offre.get("id") for f in data.get("favoris", [])):
            data.setdefault("favoris", []).append({**req.offre, "sauvegarde_le": datetime.now().isoformat()})
        sauver_user(req.user_id, data)
        return {"success": True, "total": len(data["favoris"])}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/favoris/supprimer")
def supprimer_favori(req: SauvegardeOffre, user=Depends(verifier_token)):
    try:
        data = charger_user(req.user_id)
        data["favoris"] = [f for f in data.get("favoris", []) if f.get("id") != req.offre.get("id")]
        sauver_user(req.user_id, data)
        return {"success": True}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/favoris/{user_id}")
def get_favoris(user_id: str, user=Depends(verifier_token)):
    try:
        return {"success": True, "favoris": charger_user(user_id).get("favoris", [])}
    except Exception as e:
        raise HTTPException(500, str(e))

# ── Candidatures ──
@app.post("/candidatures/maj")
def maj_candidature(req: MajCandidature, user=Depends(verifier_token)):
    try:
        data = charger_user(req.user_id)
        cands = data.setdefault("candidatures", [])
        existing = next((c for c in cands if c.get("offre_id") == req.offre_id), None)
        now = datetime.now().isoformat()
        if existing:
            existing["statut"] = req.statut
            existing["maj_le"] = now
        else:
            cands.append({"offre_id": req.offre_id, "offre": req.offre or {}, "statut": req.statut, "cree_le": now, "maj_le": now})
        sauver_user(req.user_id, data)
        return {"success": True}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/candidatures/{user_id}")
def get_candidatures(user_id: str, user=Depends(verifier_token)):
    try:
        data = charger_user(user_id)
        cands = data.get("candidatures", [])
        entretiens = len([c for c in cands if c.get("statut") == "entretien"])
        return {"success": True, "candidatures": cands, "stats": {"total": len(cands), "entretiens": entretiens, "taux": round(entretiens/len(cands)*100 if cands else 0, 1)}}
    except Exception as e:
        raise HTTPException(500, str(e))
