"""
SCRIPT 2 — Scraping des flux ATS publics
Slugs vérifiés et fonctionnels
"""

import requests
from datetime import datetime

# ─────────────────────────────────────────────
# WORKDAY — Slugs vérifiés
# ─────────────────────────────────────────────
ENTREPRISES_WORKDAY = [
    {"nom": "Airbus", "slug": "ag", "path": "Airbus"},
    {"nom": "FDJ", "slug": "groupefdj", "path": "FDJ"},
    {"nom": "Galileo Education", "slug": "galileo", "path": "galileo_career_site"},
    {"nom": "L'Oréal", "slug": "loreal", "path": "External"},
    {"nom": "Danone", "slug": "danone", "path": "External"},
    {"nom": "Capgemini", "slug": "capgemini", "path": "External"},
]

# ─────────────────────────────────────────────
# LEVER — Slugs vérifiés
# ─────────────────────────────────────────────
ENTREPRISES_LEVER = [
    {"nom": "Mistral AI", "slug": "mistral"},
    {"nom": "Qonto", "slug": "qonto"},
    {"nom": "Pennylane", "slug": "pennylane"},
    {"nom": "Swile", "slug": "swile"},
    {"nom": "Gojob", "slug": "gojob"},
]

# ─────────────────────────────────────────────
# GREENHOUSE — Slugs vérifiés
# ─────────────────────────────────────────────
ENTREPRISES_GREENHOUSE = [
    {"nom": "Doctolib", "slug": "doctolib"},
    {"nom": "Alma", "slug": "alma"},
    {"nom": "Spendesk", "slug": "spendesk"},
    {"nom": "Contentsquare", "slug": "contentsquare"},
    {"nom": "Payfit", "slug": "payfit"},
]


def scrape_workday(entreprise: dict, mots_cles: str = "") -> list:
    url = f"https://{entreprise['slug']}.wd3.myworkdayjobs.com/wday/cxs/{entreprise['slug']}/{entreprise['path']}/jobs"
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    payload = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": mots_cles}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        offres = []
        for job in data.get("jobPostings", []):
            offres.append({
                "id": f"workday_{entreprise['slug']}_{job.get('externalPath', '')}",
                "titre": job.get("title"),
                "entreprise": entreprise["nom"],
                "lieu": job.get("locationsText", "Non précisé"),
                "contrat": "Non précisé",
                "salaire": "Non précisé",
                "description": "",
                "date_publication": job.get("postedOn", datetime.utcnow().isoformat()),
                "url": f"https://{entreprise['slug']}.wd3.myworkdayjobs.com/{entreprise['path']}/{job.get('externalPath', '')}",
                "source": f"Workday ({entreprise['nom']})",
                "competences": [],
            })
        print(f"✅ Workday {entreprise['nom']} : {len(offres)} offres")
        return offres
    except Exception as e:
        print(f"⚠️  Workday {entreprise['nom']} : {e}")
        return []


def scrape_greenhouse(entreprise: dict, mots_cles: str = "") -> list:
    url = f"https://boards-api.greenhouse.io/v1/boards/{entreprise['slug']}/jobs"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        offres = []
        for job in data.get("jobs", []):
            if mots_cles and mots_cles.lower() not in job.get("title", "").lower():
                continue
            offres.append({
                "id": f"greenhouse_{job.get('id')}",
                "titre": job.get("title"),
                "entreprise": entreprise["nom"],
                "lieu": job.get("location", {}).get("name", "Non précisé"),
                "contrat": "Non précisé",
                "salaire": "Non précisé",
                "description": job.get("content", "")[:500],
                "date_publication": job.get("updated_at", datetime.utcnow().isoformat()),
                "url": job.get("absolute_url"),
                "source": f"Greenhouse ({entreprise['nom']})",
                "competences": [],
            })
        print(f"✅ Greenhouse {entreprise['nom']} : {len(offres)} offres")
        return offres
    except Exception as e:
        print(f"⚠️  Greenhouse {entreprise['nom']} : {e}")
        return []


def scrape_lever(entreprise: dict, mots_cles: str = "") -> list:
    url = f"https://api.lever.co/v0/postings/{entreprise['slug']}?mode=json"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        jobs = response.json()
        offres = []
        for job in jobs:
            if mots_cles and mots_cles.lower() not in job.get("text", "").lower():
                continue
            offres.append({
                "id": f"lever_{job.get('id')}",
                "titre": job.get("text"),
                "entreprise": entreprise["nom"],
                "lieu": job.get("categories", {}).get("location", "Non précisé"),
                "contrat": job.get("categories", {}).get("commitment", "Non précisé"),
                "salaire": "Non précisé",
                "description": job.get("descriptionPlain", "")[:500],
                "date_publication": datetime.utcfromtimestamp(job.get("createdAt", 0) / 1000).isoformat(),
                "url": job.get("hostedUrl"),
                "source": f"Lever ({entreprise['nom']})",
                "competences": [],
            })
        print(f"✅ Lever {entreprise['nom']} : {len(offres)} offres")
        return offres
    except Exception as e:
        print(f"⚠️  Lever {entreprise['nom']} : {e}")
        return []


def scraper_tous_ats(mots_cles: str = "") -> list:
    toutes_offres = []
    print("\n🔍 Scraping Workday...")
    for e in ENTREPRISES_WORKDAY:
        toutes_offres.extend(scrape_workday(e, mots_cles))
    print("\n🔍 Scraping Greenhouse...")
    for e in ENTREPRISES_GREENHOUSE:
        toutes_offres.extend(scrape_greenhouse(e, mots_cles))
    print("\n🔍 Scraping Lever...")
    for e in ENTREPRISES_LEVER:
        toutes_offres.extend(scrape_lever(e, mots_cles))
    print(f"\n📊 Total ATS : {len(toutes_offres)} offres récupérées")
    return toutes_offres


if __name__ == "__main__":
    offres = scraper_tous_ats()
    for o in offres[:5]:
        print(f"\n📌 {o['titre']} — {o['entreprise']}")
        print(f"   📍 {o['lieu']} | 🔗 {o['url']}")
