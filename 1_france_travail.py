import os
import requests
import json
from datetime import datetime

# Ne jamais committer les vraies valeurs — utiliser les variables d'environnement
CLIENT_ID = os.environ.get("CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "")

def get_access_token():
    if not CLIENT_ID or not CLIENT_SECRET:
        raise ValueError("CLIENT_ID et CLIENT_SECRET France Travail doivent être définis (variables d'environnement)")
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
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    params = {
        "motsCles": criteres.get("motsCles", ""),
        "range": f"0-{criteres.get('nbResultats', 10) - 1}",
        "sort": "1"
    }
    if criteres.get("typeContrat"):
        params["typeContrat"] = criteres["typeContrat"]
    if criteres.get("distance"):
        params["distance"] = criteres["distance"]

    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    data = response.json()
    offres = data.get("resultats", [])

    offres_normalisees = []
    for offre in offres:
        offres_normalisees.append({
            "id": offre.get("id"),
            "titre": offre.get("intitule"),
            "entreprise": offre.get("entreprise", {}).get("nom", "Non précisé"),
            "lieu": offre.get("lieuTravail", {}).get("libelle"),
            "contrat": offre.get("typeContratLibelle"),
            "salaire": offre.get("salaire", {}).get("libelle", "Non précisé"),
            "description": offre.get("description", ""),
            "date_publication": offre.get("dateCreation"),
            "url": offre.get("origineOffre", {}).get("urlOrigine", f"https://www.francetravail.fr/offres/emploi/offre/{offre.get('id')}"),
            "source": "France Travail",
            "competences": [c.get("libelle") for c in offre.get("competences", [])],
        })

    print(f"✅ {len(offres_normalisees)} offres récupérées depuis France Travail")
    return offres_normalisees


def get_offres_recentes(criteres: dict, depuis_minutes: int = 10) -> list:
    """Retourne les offres dont la date de publication est dans les N dernières minutes."""
    from datetime import datetime, timezone, timedelta
    toutes = rechercher_offres(criteres)
    if depuis_minutes <= 0:
        return toutes
    seuil = datetime.now(timezone.utc) - timedelta(minutes=depuis_minutes)
    recentes = []
    for o in toutes:
        dp = o.get("date_publication")
        if not dp:
            continue
        try:
            if isinstance(dp, str) and "T" in dp:
                dt = datetime.fromisoformat(dp.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(str(dp).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= seuil:
                recentes.append(o)
        except Exception:
            pass
    return recentes


if __name__ == "__main__":
    criteres_test = {
        "motsCles": "developpeur python",
        "typeContrat": "CDI",
        "nbResultats": 5
    }
    offres = rechercher_offres(criteres_test)
    for o in offres:
        print(f"\n📌 {o['titre']} — {o['entreprise']}")
        print(f"   📍 {o['lieu']} | 💰 {o['salaire']}")
        print(f"   🔗 {o['url']}")
