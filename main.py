from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
import json, os, requests, re, time, hashlib, threading, smtplib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import jwt

LBA_API_KEY = os.environ.get("LBA_API_KEY", "eyJhbGciOiJIUzI1NiJ9.eyJfaWQiOiI2OWIyMWNjYjVhZTczYTE3MWE0YTBiMTAiLCJhcGlfa2V5IjoidmJEbWhma0RVLzVrMVRCaStGa1ByRnNsRlgwSUJBKzNaT0F5ZmJWazAvUT0iLCJvcmdhbmlzYXRpb24iOm51bGwsImVtYWlsIjoia2FyaW1iYXJlazI1QGdtYWlsLmNvbSIsImlzcyI6ImFwaSIsImlhdCI6MTc3MzI4MDQ2OSwiZXhwIjoxODA0ODE2NDY5fQ.OEzLnBklaxAUf3uaOMg8nmL_amZ53FOy5ORjjCi0xE0")


# ══════════════════════════════════════════════
# 🗄️  CACHE MÉMOIRE (TTL 15 min)
# ══════════════════════════════════════════════
_cache_offres: dict = {}          # {clé: {"ts": float, "data": list, "erreurs": list}}
_cache_lock = threading.Lock()
CACHE_TTL = 900  # 15 minutes

def _cache_key(mots: str, localisation: str, contrat: str) -> str:
    raw = f"{mots.lower().strip()}|{localisation.lower().strip()}|{contrat.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()

def cache_get(mots: str, localisation: str, contrat: str):
    key = _cache_key(mots, localisation, contrat)
    with _cache_lock:
        entry = _cache_offres.get(key)
        if entry and (time.time() - entry["ts"]) < CACHE_TTL:
            return entry["data"], entry["erreurs"], True  # (data, erreurs, hit)
    return None, None, False

def cache_set(mots: str, localisation: str, contrat: str, data: list, erreurs: list):
    key = _cache_key(mots, localisation, contrat)
    with _cache_lock:
        _cache_offres[key] = {"ts": time.time(), "data": data, "erreurs": erreurs}

def cache_clear():
    with _cache_lock:
        _cache_offres.clear()

# Variables SMTP (optionnelles — pour alertes email)
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "noreply@jobalert.app")

app = FastAPI(title="JobAlert IA", version="9.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

security = HTTPBearer()
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")

_jwks_client = None
def get_jwks_client():
    global _jwks_client
    if _jwks_client is None and SUPABASE_URL:
        try:
            from jwt import PyJWKClient
            _jwks_client = PyJWKClient(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json")
        except (ImportError, Exception):
            pass
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

class SauvegardeCV(BaseModel):
    user_id: str
    cv_texte: str
    cv_base64: Optional[str] = None

class DemandeAdapterLettre(BaseModel):
    profil: dict
    offre: dict
    lm_base: str  # LM personnelle de l'utilisateur

class DemandePackageComplet(BaseModel):
    profil: dict
    offre: dict
    lm_base: Optional[str] = None

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
# Correspondance villes → codes postaux pour l'API France Travail
# L'API attend commune=CODE_POSTAL (ex: "13000" pour Marseille)
CODES_POSTAUX = {
    "paris": "75000", "marseille": "13000", "lyon": "69000", "toulouse": "31000",
    "nice": "06000", "nantes": "44000", "montpellier": "34000", "strasbourg": "67000",
    "bordeaux": "33000", "lille": "59000", "rennes": "35000", "reims": "51000",
    "saint-etienne": "42000", "toulon": "83000", "grenoble": "38000", "dijon": "21000",
    "angers": "49000", "nimes": "30000", "villeurbanne": "69100", "le mans": "72000",
    "aix-en-provence": "13100", "clermont-ferrand": "63000", "brest": "29000",
    "limoges": "87000", "tours": "37000", "amiens": "80000", "perpignan": "66000",
    "metz": "57000", "besancon": "25000", "orleans": "45000", "mulhouse": "68100",
    "rouen": "76000", "caen": "14000", "nancy": "54000", "argenteuil": "95100",
    "montreuil": "93100", "roubaix": "59100", "tourcoing": "59200", "avignon": "84000",
    "versailles": "78000", "poitiers": "86000", "pau": "64000", "calais": "62100",
    "colmar": "68000", "lorient": "56100", "troyes": "10000", "annecy": "74000",
    "saint-denis": "93200", "vitry-sur-seine": "94400", "le havre": "76600",
}

def ville_vers_code_postal(ville: str) -> str:
    """Convertit un nom de ville en code postal pour l'API France Travail"""
    import unicodedata, re
    def norm(s):
        s = unicodedata.normalize("NFD", s)
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        return re.sub(r"[-'_]", " ", s.lower()).strip()
    # Si déjà un code postal (5 chiffres), le retourner directement
    v = norm(ville)
    if re.match(r"^[0-9]{5}$", v):
        return v
    return CODES_POSTAUX.get(v, "")

def scraper_ft(criteres: dict):
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    # range max = 149 (limitation API France Travail)
    params = {
        "motsCles": criteres.get("motsCles", ""),
        "range": "0-149",
        "sort": "1"  # tri par date
    }
    if criteres.get("typeContrat"):
        params["typeContrat"] = criteres["typeContrat"]
    if criteres.get("localisation"):
        cp = ville_vers_code_postal(criteres["localisation"])
        if cp:
            # L'API France Travail accepte departement (2 chiffres) mais pas commune
            params["departement"] = cp[:2]
    r = requests.get(
        "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search",
        headers=headers, params=params, timeout=20
    )
    if not r.ok:
        raise Exception(f"FT {r.status_code}: {r.text[:200]}")
    data = r.json()
    resultats = data.get("resultats", [])
    return [offre(
        o.get("id"), o.get("intitule"), o.get("entreprise", {}).get("nom"),
        o.get("lieuTravail", {}).get("libelle"), o.get("typeContratLibelle"),
        o.get("salaire", {}).get("libelle"), o.get("description"), o.get("dateCreation"),
        o.get("origineOffre", {}).get("urlOrigine", f"https://www.francetravail.fr/offres/emploi/offre/{o.get('id')}"),
        "France Travail", [c.get("libelle") for c in o.get("competences", [])]
    ) for o in resultats]

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
    {"nom": "Spendesk", "slug": "spendesk"},
    {"nom": "Aircall", "slug": "aircall"},
    {"nom": "Ankorstore", "slug": "ankorstore"},
    # Business Planning
    {"nom": "Pigment", "slug": "pigment"},
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
    {"nom": "Younited", "slug": "younited"},
    {"nom": "iBanFirst", "slug": "ibanfirst"},
    # AdTech
    {"nom": "Teads", "slug": "teads1"},
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
    # Services / Propreté / Facility
    {"nom": "Onet", "slug": "Onet"},
    {"nom": "ISS France", "slug": "ISSFrance"},
    {"nom": "Elior", "slug": "Elior"},
    {"nom": "Elis", "slug": "Elis"},
    # Grande distribution alimentaire
    {"nom": "Casino", "slug": "CasinoGroup"},
    {"nom": "Picard", "slug": "Picard"},
    # Santé / Médico-social
    {"nom": "Korian", "slug": "Korian"},
    {"nom": "Orpea", "slug": "Orpea"},
    {"nom": "Ramsay Santé", "slug": "RamsaySante"},
    {"nom": "Elsan", "slug": "Elsan"},
    # Transport / Mobilité
    {"nom": "Transdev", "slug": "Transdev"},
    {"nom": "Keolis", "slug": "Keolis"},
    {"nom": "DB Schenker France", "slug": "DBSchenker"},
    # RH / Interim supplémentaires
    {"nom": "Randstad France", "slug": "RandstadFrance"},
    {"nom": "Synergie", "slug": "Synergie"},
    {"nom": "Proman", "slug": "Proman"},
    # Assurance supplémentaire
    {"nom": "Groupama", "slug": "Groupama"},
    {"nom": "Allianz France", "slug": "AllianzFrance"},
    {"nom": "Generali France", "slug": "GeneraliFrance"},
    # Distribution spécialisée
    {"nom": "Kiloutou", "slug": "Kiloutou"},
    {"nom": "Norauto", "slug": "Norauto"},
    # Hôtellerie / Restauration
    {"nom": "Marriott France", "slug": "Marriott"},
    {"nom": "Hyatt France", "slug": "Hyatt"},
    {"nom": "Courtepaille", "slug": "Courtepaille"},
    # LegalTech
    {"nom": "Legalstart", "slug": "Legalstart"},
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
    # Services / RH
    {"nom": "Adecco Group", "tenant": "adeccogroup", "path": "AdeccoGroup"},
    {"nom": "Manpower Group", "tenant": "manpowergroup", "path": "ManpowerGroup"},
    {"nom": "Bureau Veritas", "tenant": "bureauveritas", "path": "BureauVeritas"},
    # Retail / Distribution
    {"nom": "Leroy Merlin (WD)", "tenant": "leroymerlin", "path": "LeroyMerlin"},
    {"nom": "Fnac Darty (WD)", "tenant": "fnacdarty", "path": "FnacDarty"},
    # Santé
    {"nom": "Sanofi (WD)", "tenant": "sanofi", "path": "Sanofi"},
    {"nom": "bioMérieux", "tenant": "biomerieux", "path": "bioMerieux"},
    # Industrie
    {"nom": "Plastic Omnium", "tenant": "plasticomnium", "path": "PlasticOmnium"},
    {"nom": "Eiffage", "tenant": "eiffage", "path": "Eiffage"},
    {"nom": "Air Liquide", "tenant": "airliquidehr", "path": "AirLiquideExternalCareer"},
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

# ── ASHBY (API JSON publique — startups tech FR) ──
# Slugs 100% vérifiés sur jobs.ashbyhq.com
ASHBY_ENTREPRISES = [
    {"nom": "Alan", "slug": "alan"},
    {"nom": "Joko", "slug": "joko"},
]

# ── PERSONIO (XML public — PME/ETI françaises) ──
# Slugs vérifiés sur {company}.jobs.personio.de
# Luko supprimée (liquidée 2023, reprise Allianz)
# Meero supprimée (restructuration massive 2022, recrutements quasi nuls)
PERSONIO_ENTREPRISES = [
    {"nom": "Agicap", "company": "agicap"},
    {"nom": "Pricemoov", "company": "pricemoov"},
    {"nom": "Libeo", "company": "libeo"},
    {"nom": "Payplug", "company": "payplug"},
    {"nom": "Scality", "company": "scality"},
    {"nom": "Sendinblue", "company": "sendinblue"},
    {"nom": "Livestorm", "company": "livestorm"},
    {"nom": "Wimi", "company": "wimi"},
    {"nom": "Botify", "company": "botify"},
    {"nom": "Spendesk", "company": "spendesk"},
    {"nom": "Partoo", "company": "partoo"},
    {"nom": "Getfluence", "company": "getfluence"},
    {"nom": "Sociabble", "company": "sociabble"},
]

# ══════════════════════════════════════════════
# 🟣  ASHBY (API JSON publique, aucune auth)
# ══════════════════════════════════════════════
def scraper_ashby_one(e: dict, mots: str = "") -> list:
    result = []
    try:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{e['slug']}"
        r = requests.get(url, headers=H_JSON, timeout=10)
        if r.status_code != 200:
            return result
        for j in r.json().get("jobs", []):
            if not j.get("isListed", True):
                continue
            titre = j.get("title", "")
            if not match(titre, mots):
                continue
            loc = j.get("location", "") or ""
            addr = j.get("address", {}).get("postalAddress", {})
            lieu = loc or ", ".join(filter(None, [
                addr.get("addressLocality"), addr.get("addressCountry")
            ])) or "Non précisé"
            result.append(offre(
                f"ashby_{j.get('id', titre)}", titre, e["nom"],
                lieu,
                j.get("employmentType", "").replace("FullTime", "CDI").replace("Intern", "Stage").replace("Contract", "CDD"),
                None, j.get("descriptionPlain", ""),
                j.get("publishedAt"), j.get("jobUrl"), f"Site carrière ({e['nom']})"
            ))
    except Exception:
        pass
    return result

def scraper_ashby(entreprises: list, mots: str = "") -> list:
    result = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(scraper_ashby_one, e, mots): e for e in entreprises}
        for f in as_completed(futures):
            try:
                result.extend(f.result())
            except Exception:
                pass
    return result

# ══════════════════════════════════════════════
# 🟤  PERSONIO (XML public par entreprise)
# ══════════════════════════════════════════════
def scraper_personio_one(e: dict, mots: str = "") -> list:
    result = []
    try:
        url = f"https://{e['company']}.jobs.personio.de/xml?language=fr"
        r = requests.get(url, headers=H_BROWSER, timeout=10)
        if r.status_code != 200:
            return result
        root = ET.fromstring(r.content)
        for pos in root.findall(".//position"):
            titre = (pos.findtext("name") or "").strip()
            if not titre or not match(titre, mots):
                continue
            lieu = (pos.findtext("office") or pos.findtext("location") or "Non précisé").strip()
            contrat = (pos.findtext("schedule") or "").strip()
            desc = (pos.findtext("jobDescriptions/jobDescription/value") or "").strip()
            job_id = pos.findtext("id") or titre
            url_offre = f"https://{e['company']}.jobs.personio.de/job/{job_id}"
            result.append(offre(
                f"personio_{e['company']}_{job_id}", titre, e["nom"],
                lieu, contrat, None, desc,
                pos.findtext("createdAt") or None,
                url_offre, f"Site carrière ({e['nom']})"
            ))
    except Exception:
        pass
    return result

def scraper_personio(entreprises: list, mots: str = "") -> list:
    result = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(scraper_personio_one, e, mots): e for e in entreprises}
        for f in as_completed(futures):
            try:
                result.extend(f.result())
            except Exception:
                pass
    return result

# ══════════════════════════════════════════════
# 🟢  LA BONNE ALTERNANCE (API beta.gouv — alternance/stage)
# Nécessite LBA_API_KEY — usage non lucratif uniquement
# ══════════════════════════════════════════════
# Mapping villes → coordonnées (lat, lon) pour La Bonne Alternance
LBA_COORDS = {
    "paris": (48.8566, 2.3522), "marseille": (43.2965, 5.3698),
    "lyon": (45.7640, 4.8357), "toulouse": (43.6047, 1.4442),
    "nice": (43.7102, 7.2620), "nantes": (47.2184, -1.5536),
    "bordeaux": (44.8378, -0.5792), "lille": (50.6292, 3.0573),
    "montpellier": (43.6108, 3.8767), "strasbourg": (48.5734, 7.7521),
    "rennes": (48.1173, -1.6778), "grenoble": (45.1885, 5.7245),
    "aix-en-provence": (43.5297, 5.4474), "toulon": (43.1242, 5.9280),
    "dijon": (47.3220, 5.0415), "angers": (47.4784, -0.5632),
    "reims": (49.2583, 4.0317), "le mans": (47.9960, 0.1966),
    "clermont-ferrand": (45.7797, 3.0863), "brest": (48.3904, -4.4861),
    "amiens": (49.8941, 2.2957), "rouen": (49.4432, 1.0993),
    "caen": (49.1829, -0.3707), "nancy": (48.6921, 6.1844),
    "metz": (49.1193, 6.1757), "tours": (47.3941, 0.6848),
}

def scraper_lba(mots: str = "", localisation: str = "", contrat: str = "") -> list:
    """La Bonne Alternance — uniquement pour contrats alternance/stage"""
    if not LBA_API_KEY:
        return []
    # On ne lance LBA que si le type de contrat est alternance/stage ou non précisé
    contrat_lower = (contrat or "").lower()
    if contrat_lower and contrat_lower not in ("", "al", "st", "alternance", "stage", "apprentissage"):
        return []
    result = []
    try:
        headers = {"Authorization": f"Bearer {LBA_API_KEY}", "Accept": "application/json"}
        params = {"caller": "jobalert"}
        # Géolocalisation
        ville_norm = (localisation or "").lower().strip()
        import unicodedata, re as _re
        def norm_ville(s):
            s = unicodedata.normalize("NFD", s)
            s = "".join(c for c in s if unicodedata.category(c) != "Mn")
            return _re.sub(r"[-'_]", " ", s.lower()).strip()
        ville_key = norm_ville(localisation) if localisation else ""
        coords = LBA_COORDS.get(ville_key)
        if coords:
            params["latitude"] = coords[0]
            params["longitude"] = coords[1]
            params["radius"] = 30
        r = requests.get(
            "https://api.apprentissage.beta.gouv.fr/api/job/v1/search",
            headers=headers, params=params, timeout=15
        )
        if r.status_code != 200:
            return []
        data = r.json()
        # Offres LBA directes
        for j in data.get("jobs", [])[:30]:
            titre = (j.get("offer", {}).get("title") or "").strip()
            if not titre or not match(titre, mots):
                continue
            workplace = j.get("workplace", {})
            contract = j.get("contract", {})
            contrat_type = contract.get("type") or "Alternance"
            lieu = workplace.get("location", {}).get("label") or workplace.get("name") or "Non précisé"
            desc = j.get("offer", {}).get("description", "")
            apply_url = j.get("apply", {}).get("url") or "#"
            job_id = j.get("identifier", {}).get("partner_job_id") or titre[:20]
            result.append(offre(
                f"lba_{job_id}", titre,
                workplace.get("name", "Non précisé"), lieu,
                contrat_type,
                None, desc,
                j.get("contract", {}).get("start") or None,
                apply_url, "La Bonne Alternance"
            ))
    except Exception:
        pass
    return result

# ══════════════════════════════════════════════
# 🚀  SCRAPER PRINCIPAL (parallélisé)
# ══════════════════════════════════════════════
# Timeout individuel par scraper (secondes)
SCRAPER_TIMEOUTS = {
    "Lever": 10, "Greenhouse": 10, "SmartRecruiters": 12,
    "Workday": 12, "Welcome to the Jungle": 10, "Portails HTML": 10,
    "Ashby": 10, "Personio": 10, "La Bonne Alternance": 12,
}

def scraper_tous(mots: str = "", localisation: str = "", type_contrat: str = ""):
    """Lance tous les scrapers en parallèle — timeout individuel par source — résultats partiels si timeout"""
    toutes = []
    erreurs = []
    sources_ok = []
    sources_timeout = []

    scrapers = [
        ("Lever", lambda: scraper_lever(LEVER_ENTREPRISES, mots)),
        ("Greenhouse", lambda: scraper_greenhouse(GREENHOUSE_ENTREPRISES, mots)),
        ("SmartRecruiters", lambda: scraper_smartrecruiters(SMARTRECRUITERS_ENTREPRISES, mots)),
        ("Workday", lambda: scraper_workday(WORKDAY_ENTREPRISES, mots)),
        ("Welcome to the Jungle", lambda: scraper_wttj(mots, localisation)),
        ("Portails HTML", lambda: scraper_html(HTML_ENTREPRISES, mots)),
        ("Ashby", lambda: scraper_ashby(ASHBY_ENTREPRISES, mots)),
        ("Personio", lambda: scraper_personio(PERSONIO_ENTREPRISES, mots)),
        ("La Bonne Alternance", lambda: scraper_lba(mots, localisation, type_contrat)),
    ]

    with ThreadPoolExecutor(max_workers=9) as ex:
        futures = {ex.submit(fn): nom for nom, fn in scrapers}
        for future in as_completed(futures, timeout=25):
            nom = futures[future]
            tmax = SCRAPER_TIMEOUTS.get(nom, 12)
            try:
                res = future.result(timeout=tmax)
                toutes.extend(res)
                sources_ok.append(f"{nom}:{len(res)}")
            except FuturesTimeoutError:
                sources_timeout.append(nom)
                erreurs.append(f"{nom}: timeout ({tmax}s)")
            except Exception as e:
                erreurs.append(f"{nom}: {str(e)}")

    if sources_timeout:
        erreurs.insert(0, f"Sources en timeout (résultats partiels): {', '.join(sources_timeout)}")

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

# Cache des variantes de postes pour éviter les appels GPT répétés
_cache_variantes = {}

def expand_mots_cles(poste: str) -> list:
    """Génère toutes les variantes/synonymes du poste via GPT — mis en cache"""
    if not poste: return [poste]
    key = poste.lower().strip()
    if key in _cache_variantes:
        return _cache_variantes[key]
    try:
        client = get_openai_client()
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"""Tu es un expert du marché de l'emploi français.
Pour le domaine/poste "{poste}", génère toutes les appellations et variantes de postes couramment utilisées dans les offres d'emploi françaises.
Réponds UNIQUEMENT avec un JSON strict : {{"variantes": ["variante1", "variante2", ...]}}
Inclus : abréviations (RRH, DRH...), appellations longues, niveaux (assistant, chargé, responsable, directeur...), synonymes sectoriels.
Maximum 20 variantes pertinentes."""}],
            temperature=0.1, response_format={"type": "json_object"}
        )
        data = json.loads(r.choices[0].message.content)
        variantes = data.get("variantes", [poste])
        # Toujours inclure le terme original
        if poste.lower() not in [v.lower() for v in variantes]:
            variantes.insert(0, poste)
        _cache_variantes[key] = variantes
        return variantes
    except:
        return [poste]

def scorer(profil: dict, o: dict):
    client = get_openai_client()
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"""Tu es un expert RH. Évalue la compatibilité entre ce profil et cette offre d'emploi.
Réponds UNIQUEMENT en JSON strict :
{{"score":75,"points_forts":["raison 1","raison 2"],"points_faibles":["manque 1"],"recommandation":"conseil court"}}

RÈGLES DE SCORING :
- Le score évalue UNIQUEMENT la compatibilité profil ↔ compétences requises du poste
- Base-toi sur : niveau d'expérience, formation, compétences, dernier poste
- Un score > 80 = profil très solide pour ce type de poste
- Un score < 50 = profil clairement inadapté aux exigences du poste
- Sois précis et objectif, pas complaisant

PROFIL : {profil.get("nom","")} | {profil.get("annees_experience",0)} ans exp. | Dernier poste : {profil.get("dernier_poste","")} | Formation : {profil.get("formation","")} | Compétences : {", ".join(profil.get("competences",[])[:10])} | {profil.get("resume_profil","")[:200]}
OFFRE : {o.get("titre","")} chez {o.get("entreprise","")} | {o.get("description","")[:500]}"""}],
        temperature=0.1, response_format={"type": "json_object"}
    )
    return json.loads(r.choices[0].message.content)


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
    mx, my = 70, 70
    y = my
    if nom_candidat:
        page.insert_text((mx, y), nom_candidat, fontsize=13, fontname="helv", color=(0.1, 0.1, 0.4))
        y += 22
    if entreprise or titre_offre:
        label = f"Candidature : {titre_offre}" + (f" — {entreprise}" if entreprise else "")
        page.insert_text((mx, y), label, fontsize=10, fontname="helv", color=(0.4, 0.4, 0.4))
        y += 16
    from datetime import date
    page.insert_text((mx, y), f"Le {date.today().strftime('%d/%m/%Y')}", fontsize=10, fontname="helv", color=(0.4,0.4,0.4))
    y += 30
    page.draw_line((mx, y), (595 - mx, y), color=(0.8, 0.8, 0.8), width=0.5)
    y += 20
    for paragraphe in texte_lm.split("\n"):
        if not paragraphe.strip():
            y += 10
            continue
        mots = paragraphe.split(" ")
        ligne = ""
        for mot in mots:
            test = ligne + (" " if ligne else "") + mot
            if len(test) > 90:
                page.insert_text((mx, y), ligne, fontsize=11, fontname="helv", color=(0,0,0))
                y += 16
                ligne = mot
                if y > 800:
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


def charger_user(user_id: str) -> dict:
    """Charge les données d'un utilisateur — retourne un dict vide si inexistant ou corrompu"""
    default = {"profil": {}, "criteres": {}, "favoris": [], "candidatures": [], "cv_texte": "", "cv_base64": ""}
    try:
        f = f"data_{user_id}.json"
        if os.path.exists(f):
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            # S'assurer que toutes les clés existent
            for k, v in default.items():
                data.setdefault(k, v)
            return data
        return default
    except Exception:
        return default

def sauver_user(user_id: str, data: dict):
    try:
        with open(f"data_{user_id}.json", "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
    except Exception as e:
        raise Exception(f"Impossible de sauvegarder les données : {str(e)}")

# ══════════════════════════════════════════════
# 🌐  ROUTES API
# ══════════════════════════════════════════════

@app.get("/")
def root():
    return {"message": "JobAlert IA API v9.0 — En ligne ✅", "sources": ["France Travail", "Lever", "Greenhouse", "SmartRecruiters", "Workday", "Welcome to the Jungle", "Ashby", "Personio", "La Bonne Alternance", "Portails HTML"]}

@app.get("/debug/ft")
def debug_ft():
    """Route de debug pour tester France Travail — teste plusieurs formats de commune"""
    try:
        token = get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        resultats_tests = {}
        # Test 1 : sans localisation (pour vérifier que le token marche)
        r0 = requests.get("https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search",
            headers=headers, params={"motsCles": "RH", "range": "0-4"}, timeout=15)
        resultats_tests["sans_localisation"] = {"status": r0.status_code, "nb": len(r0.json().get("resultats",[])), "erreur": r0.json().get("message")}
        # Test 2 : avec departement=13
        r1 = requests.get("https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search",
            headers=headers, params={"motsCles": "RH", "departement": "13", "range": "0-49"}, timeout=15)
        d1 = r1.json()
        resultats_tests["departement_13"] = {"status": r1.status_code, "nb": len(d1.get("resultats",[])), "erreur": d1.get("message"), "exemple": d1.get("resultats",[{}])[0].get("intitule","—") if d1.get("resultats") else "aucun"}
        # Test 3 : avec commune=13055 (code INSEE)
        r2 = requests.get("https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search",
            headers=headers, params={"motsCles": "RH", "commune": "13055", "range": "0-4"}, timeout=15)
        resultats_tests["commune_insee_13055"] = {"status": r2.status_code, "nb": len(r2.json().get("resultats",[])), "erreur": r2.json().get("message")}
        # Test 4 : avec lieuTravail.commune (format différent)
        r3 = requests.get("https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search",
            headers=headers, params={"motsCles": "RH", "commune": "13", "range": "0-4"}, timeout=15)
        resultats_tests["commune_dept_13"] = {"status": r3.status_code, "nb": len(r3.json().get("resultats",[])), "erreur": r3.json().get("message")}
        return resultats_tests
    except Exception as e:
        return {"erreur": str(e)}

@app.get("/debug/lba")
def debug_lba():
    """Test La Bonne Alternance — vérifie le token et retourne quelques offres (API v2)"""
    try:
        headers = {"Authorization": f"Bearer {LBA_API_KEY}", "Accept": "application/json"}
        r = requests.get(
            "https://api.apprentissage.beta.gouv.fr/api/job/v1/search",
            headers=headers,
            params={
                "latitude": 43.2965,
                "longitude": 5.3698,
                "radius": 30,
                "sources": "offres_emploi_lba,offres_emploi_partenaires"
            },
            timeout=15
        )
        data = r.json() if r.ok else {}
        jobs = data.get("jobs", [])
        nb = len(jobs)
        exemple = jobs[0].get("offer", {}).get("title", "—") if nb else "aucun"
        return {"status": r.status_code, "nb_offres": nb, "exemple": exemple, "token_ok": r.ok}
    except Exception as e:
        return {"erreur": str(e)}

@app.get("/debug/ashby")
def debug_ashby():
    """Test Ashby — retourne les offres Alan"""
    try:
        r = requests.get("https://api.ashbyhq.com/posting-api/job-board/alan", headers=H_JSON, timeout=10)
        jobs = r.json().get("jobs", [])
        return {"status": r.status_code, "nb_offres": len(jobs), "exemple": jobs[0].get("title", "—") if jobs else "aucun"}
    except Exception as e:
        return {"erreur": str(e)}

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
    poste = criteres.motsCles.strip()
    page = getattr(criteres, "page", 1) or 1
    page_size = 30

    # Si poste vide → recherche générique, pas de filtre titre
    if poste:
        variantes = expand_mots_cles(poste)
        mots_recherche = variantes[0] if variantes else poste
    else:
        variantes = []
        mots_recherche = ""

    localisation = criteres.localisation or ""
    type_contrat = criteres.typeContrat or ""
    cache_hit = False

    # ── Vérifier le cache ──
    cached_data, cached_erreurs, cache_hit = cache_get(mots_recherche, localisation, type_contrat)

    if cache_hit:
        toutes = cached_data
        erreurs_ft = []
        erreurs_ats = cached_erreurs or []
    else:
        offres_ft, erreurs_ft = [], []
        try:
            criteres_ft = criteres.dict()
            criteres_ft["motsCles"] = mots_recherche
            offres_ft = scraper_ft(criteres_ft)
        except Exception as e:
            erreurs_ft = [f"France Travail: {str(e)}"]

        offres_ats, erreurs_ats = scraper_tous(
            mots=mots_recherche,
            localisation=localisation,
            type_contrat=type_contrat
        )
        toutes = offres_ft + offres_ats
        # Mettre en cache avant filtres (filtres appliqués côté affichage)
        cache_set(mots_recherche, localisation, type_contrat, toutes, erreurs_ats)

    # Filtre 1 : titre — uniquement si un poste est précisé
    if variantes:
        def titre_correspond(titre: str) -> bool:
            titre_lower = titre.lower()
            return any(v.lower() in titre_lower for v in variantes)
        toutes_filtrees = [o for o in toutes if titre_correspond(o.get("titre", ""))]
    else:
        toutes_filtrees = toutes

    # Filtre 2 : localisation — appliqué UNIQUEMENT sur les offres France Travail
    # Les ATS (Lever, Greenhouse, SmartRecruiters, Workday) sont des portails globaux :
    # leurs offres sans lieu ou avec lieu étranger sont quand même pertinentes si le titre correspond.
    # France Travail est la seule source déjà filtrée par ville via l'API (code INSEE).
    # On ne filtre donc pas les ATS par lieu pour ne pas perdre les offres locales
    # qui ont un lieu mal renseigné ("Marseille, fr", "13009 Marseille", etc.)
    # → Le filtre localisation est désactivé côté backend pour les ATS.
    # La localisation est déjà passée à France Travail via le code INSEE.

    # Filtre 3 : ancienneté — on élimine les offres de plus de 14 jours
    # Si pas de date renseignée → on garde (bénéfice du doute)
    from datetime import datetime, timezone, timedelta
    import re as _re2

    LIMITE = datetime.now(timezone.utc) - timedelta(days=14)

    def date_ok(date_str: str) -> bool:
        if not date_str or date_str.strip() == "":
            return True  # pas de date → on garde
        # Formats courants : ISO 8601, DD/MM/YYYY, YYYY-MM-DD
        formats = [
            "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d",
            "%d/%m/%Y", "%d-%m-%Y",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str[:26], fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt >= LIMITE
            except ValueError:
                continue
        return True  # format non reconnu → on garde

    # Filtre date appliqué uniquement sur France Travail (dates fiables)
    # Les ATS ont souvent des dates incorrectes ou manquantes → on ne filtre pas
    offres_ft_filtrees = [o for o in toutes_filtrees if o.get("source") != "France Travail" or date_ok(o.get("date_publication", ""))]
    toutes_filtrees = offres_ft_filtrees

    sources = {}
    for o in toutes_filtrees:
        src = o.get("source", "Autre")
        sources[src] = sources.get(src, 0) + 1

    # ── Pagination ──
    total = len(toutes_filtrees)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    end = start + page_size
    offres_page = toutes_filtrees[start:end]

    return {
        "success": True,
        "offres": offres_page,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
        "variantes": variantes,
        "sources": sources,
        "cache_hit": cache_hit,
        "erreurs": erreurs_ft + erreurs_ats,
        "debug": {
            "total_brut": len(toutes),
            "apres_filtres": total,
            "page_actuelle": page,
        }
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


@app.post("/ia/package-complet")
def route_package(demande: DemandePackageComplet, user=Depends(verifier_token)):
    """Score + LM adaptée (depuis base perso ou générée depuis zéro)"""
    try:
        s = scorer(demande.profil, demande.offre)
        if demande.lm_base and demande.lm_base.strip():
            lettre = adapter_lettre(demande.profil, demande.offre, demande.lm_base)
        else:
            lettre = generer_lettre(demande.profil, demande.offre)
        return {"success": True, "score": s, "lettre": lettre}
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
@app.post("/cv/sauvegarder")
def sauvegarder_cv(req: SauvegardeCV, user=Depends(verifier_token)):
    """Sauvegarde le CV (texte + base64) sur le serveur — persistant entre sessions"""
    try:
        data = charger_user(req.user_id)
        data["cv_texte"] = req.cv_texte
        if req.cv_base64:
            data["cv_base64"] = req.cv_base64
        sauver_user(req.user_id, data)
        return {"success": True}
    except Exception as e:
        raise HTTPException(500, str(e))

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


# ══════════════════════════════════════════════
# 🗄️  CACHE
# ══════════════════════════════════════════════

@app.post("/cache/vider")
def vider_cache(user=Depends(verifier_token)):
    """Vide le cache des offres (admin / debug)"""
    cache_clear()
    return {"success": True, "message": "Cache vidé"}

@app.get("/cache/stats")
def stats_cache(user=Depends(verifier_token)):
    with _cache_lock:
        nb = len(_cache_offres)
        details = [{"key": k[:8]+"...", "age_s": round(time.time()-v["ts"]), "nb_offres": len(v["data"])} for k,v in _cache_offres.items()]
    return {"success": True, "entrees": nb, "ttl_s": CACHE_TTL, "details": details}

# ══════════════════════════════════════════════
# 📧  ALERTES EMAIL
# ══════════════════════════════════════════════

def envoyer_email_alerte(destinataire: str, nom: str, offres: list, poste: str):
    """Envoie un email HTML avec les nouvelles offres"""
    if not SMTP_HOST or not SMTP_USER:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🎯 {len(offres)} nouvelle(s) offre(s) pour {poste} — JobAlert"
        msg["From"] = SMTP_FROM
        msg["To"] = destinataire

        offres_html = "".join([f"""
        <div style="border:1px solid #e2e8f0;border-radius:12px;padding:20px;margin-bottom:16px;background:#fff;">
            <div style="font-size:16px;font-weight:700;color:#0f172a;">{o.get('titre','—')}</div>
            <div style="color:#64748b;font-size:14px;margin:6px 0;">🏢 {o.get('entreprise','—')} &nbsp;·&nbsp; 📍 {o.get('lieu','—')} &nbsp;·&nbsp; 📄 {o.get('contrat','—')}</div>
            <a href="{o.get('url','#')}" style="display:inline-block;margin-top:10px;background:#2563eb;color:#fff;padding:8px 18px;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600;">Voir l'offre →</a>
        </div>""" for o in offres[:10]])

        html = f"""<!DOCTYPE html><html><body style="font-family:sans-serif;background:#f1f5f9;padding:24px;">
        <div style="max-width:600px;margin:0 auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
            <div style="background:#2563eb;padding:28px 32px;">
                <div style="color:#fff;font-size:24px;font-weight:800;">JobAlert 🎯</div>
                <div style="color:#bfdbfe;font-size:14px;margin-top:4px;">{len(offres)} nouvelle(s) offre(s) pour "{poste}"</div>
            </div>
            <div style="padding:28px 32px;">
                <p style="color:#64748b;margin-bottom:20px;">Bonjour {nom or 'là'} 👋,<br>Voici les offres détectées aujourd'hui :</p>
                {offres_html}
                <div style="text-align:center;margin-top:24px;">
                    <a href="https://jobalert-frontend-yrzd.vercel.app" style="background:#2563eb;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-weight:700;font-size:15px;">Accéder à mon dashboard →</a>
                </div>
            </div>
            <div style="padding:16px 32px;border-top:1px solid #e2e8f0;color:#94a3b8;font-size:12px;text-align:center;">JobAlert by KB — Tu reçois cet email car tu as activé les alertes</div>
        </div></body></html>"""

        part = MIMEText(html, "html")
        msg.attach(part)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, destinataire, msg.as_string())
        return True
    except Exception as e:
        print(f"[SMTP] Erreur envoi email: {e}")
        return False

@app.post("/alertes/configurer")
def configurer_alerte(req: AlerteEmail, user=Depends(verifier_token)):
    """Sauvegarde les préférences d'alerte email d'un utilisateur"""
    try:
        data = charger_user(req.user_id)
        data["alerte_email"] = {
            "email": req.email,
            "poste": req.poste,
            "ville": req.ville,
            "contrat": req.contrat,
            "score_min": req.score_min,
            "active": req.active,
            "cree_le": datetime.now().isoformat()
        }
        sauver_user(req.user_id, data)
        return {"success": True, "message": "Alerte configurée"}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/alertes/tester/{user_id}")
def tester_alerte(user_id: str, user=Depends(verifier_token)):
    """Lance une recherche immédiate et envoie un email de test"""
    try:
        data = charger_user(user_id)
        alerte = data.get("alerte_email", {})
        profil = data.get("profil", {})
        if not alerte.get("email"):
            raise HTTPException(400, "Pas d'alerte configurée")

        # Recherche rapide
        mots = alerte.get("poste", "")
        variantes = expand_mots_cles(mots) if mots else [mots]
        offres_ft = scraper_ft({"motsCles": variantes[0] if variantes else mots, "localisation": alerte.get("ville",""), "typeContrat": alerte.get("contrat",""), "distance": 30}) if mots else []
        offres_ats, _ = scraper_tous(mots=variantes[0] if variantes else mots, localisation=alerte.get("ville",""), type_contrat=alerte.get("contrat",""))
        toutes = offres_ft + offres_ats

        ok = envoyer_email_alerte(alerte["email"], profil.get("nom",""), toutes[:5], mots)
        return {"success": ok, "nb_offres": len(toutes), "email": alerte["email"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/alertes/{user_id}")
def get_alerte(user_id: str, user=Depends(verifier_token)):
    """Récupère la config d'alerte d'un utilisateur"""
    data = charger_user(user_id)
    return {"success": True, "alerte": data.get("alerte_email", {})}

# ══════════════════════════════════════════════
# 📊  ANALYTICS
# ══════════════════════════════════════════════

@app.get("/analytics/{user_id}")
def get_analytics(user_id: str, user=Depends(verifier_token)):
    """Statistiques complètes d'un utilisateur"""
    try:
        data = charger_user(user_id)
        cands = data.get("candidatures", [])
        favs = data.get("favoris", [])

        statuts = {"postule":0,"attente":0,"entretien":0,"refus":0}
        for c in cands:
            s = c.get("statut","postule")
            statuts[s] = statuts.get(s,0) + 1

        sources_cands = {}
        for c in cands:
            src = c.get("offre",{}).get("source","Autre")
            sources_cands[src] = sources_cands.get(src,0) + 1

        # Activité par jour (30 derniers jours)
        activite = {}
        for c in cands:
            try:
                d = datetime.fromisoformat(c.get("cree_le","")).strftime("%Y-%m-%d")
                activite[d] = activite.get(d,0) + 1
            except: pass

        entretiens = statuts.get("entretien",0)
        taux_reponse = round(entretiens/len(cands)*100,1) if cands else 0

        return {
            "success": True,
            "stats": {
                "candidatures_total": len(cands),
                "favoris_total": len(favs),
                "entretiens": entretiens,
                "taux_reponse": taux_reponse,
                "statuts": statuts,
                "sources": sources_cands,
                "activite_par_jour": activite
            }
        }
    except Exception as e:
        raise HTTPException(500, str(e))
