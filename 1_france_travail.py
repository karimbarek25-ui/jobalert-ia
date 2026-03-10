import requests
import json
from datetime import datetime

CLIENT_ID = "PAR_jobalertia_b59e2d4a190d56f20dd6dcd311f27970aba842a9a34f6a59a9f02034683e78cb"
CLIENT_SECRET = "ae82b2d6826406d16fd75a30531edd8c0633b9a08cb89d969c1f99bcba8bbcd3"

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
