"""
SCRIPT 5 — Orchestrateur principal
Lance la surveillance en continu et coordonne tous les scripts
C'est CE fichier que tu fais tourner sur ton serveur 24h/24
"""

import time
import json
import hashlib
from datetime import datetime

# Import des autres scripts
from france_travail import rechercher_offres, get_offres_recentes
from ats_scraper import scraper_tous_ats
from ia_engine import analyser_cv, scorer_compatibilite, adapter_cv, generer_lettre_motivation
from notifications import envoyer_notification_offre

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
INTERVALLE_VERIFICATION = 5 * 60   # Vérification toutes les 5 minutes
SCORE_MINIMUM_NOTIFICATION = 70    # Notifier uniquement si score >= 70%


# ─────────────────────────────────────────────
# BASE DE DONNÉES SIMPLIFIÉE (fichier JSON)
# En production : remplacer par PostgreSQL ou Supabase
# ─────────────────────────────────────────────

def charger_utilisateurs() -> list:
    """Charge la liste des utilisateurs depuis le fichier JSON"""
    try:
        with open("utilisateurs.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def charger_offres_vues() -> set:
    """Charge les IDs des offres déjà traitées pour éviter les doublons"""
    try:
        with open("offres_vues.json", "r") as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()

def sauvegarder_offres_vues(offres_vues: set):
    """Sauvegarde les IDs des offres déjà traitées"""
    with open("offres_vues.json", "w") as f:
        json.dump(list(offres_vues), f)

def sauvegarder_candidature(utilisateur_id: str, offre: dict, score: dict, cv_adapte: str, lettre: str):
    """Sauvegarde une candidature préparée dans le dashboard de l'utilisateur"""
    try:
        with open(f"candidatures_{utilisateur_id}.json", "r", encoding="utf-8") as f:
            candidatures = json.load(f)
    except FileNotFoundError:
        candidatures = []
    
    candidatures.append({
        "id": hashlib.md5(f"{offre['id']}{utilisateur_id}".encode()).hexdigest(),
        "offre": offre,
        "score": score,
        "cv_adapte": cv_adapte,
        "lettre": lettre,
        "statut": "prête",           # prête → envoyée → vue → entretien → refus → acceptée
        "date_preparation": datetime.utcnow().isoformat(),
        "date_candidature": None,
        "date_reponse": None
    })
    
    with open(f"candidatures_{utilisateur_id}.json", "w", encoding="utf-8") as f:
        json.dump(candidatures, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
# BOUCLE PRINCIPALE DE SURVEILLANCE
# ─────────────────────────────────────────────

def traiter_offre_pour_utilisateur(offre: dict, utilisateur: dict, offres_vues: set) -> bool:
    """
    Traite une offre pour un utilisateur spécifique
    Retourne True si une notification a été envoyée
    """
    # Clé unique offre + utilisateur pour éviter les doublons
    cle = f"{offre['id']}_{utilisateur['id']}"
    if cle in offres_vues:
        return False
    
    offres_vues.add(cle)
    
    # Score de compatibilité
    score = scorer_compatibilite(utilisateur["profil"], offre)
    
    if score["score"] < SCORE_MINIMUM_NOTIFICATION:
        return False
    
    print(f"\n🎯 Match trouvé ! {score['score']}% — {offre['titre']} chez {offre['entreprise']}")
    
    # Génération des documents adaptés
    cv_adapte = adapter_cv(utilisateur["profil"], offre, utilisateur["cv_original"])
    lettre = generer_lettre_motivation(utilisateur["profil"], offre)
    
    # Sauvegarde dans le dashboard
    sauvegarder_candidature(
        utilisateur["id"],
        offre,
        score,
        cv_adapte,
        lettre
    )
    
    # Envoi de la notification
    envoyer_notification_offre(
        utilisateur["email"],
        offre,
        score,
        prenom=utilisateur["profil"].get("nom", "").split()[0]
    )
    
    return True


def cycle_surveillance():
    """
    Un cycle complet de surveillance :
    1. Récupère les nouvelles offres
    2. Pour chaque utilisateur, vérifie les matchs
    3. Envoie les notifications
    """
    print(f"\n{'='*50}")
    print(f"🔍 Cycle de surveillance — {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*50}")
    
    utilisateurs = charger_utilisateurs()
    offres_vues = charger_offres_vues()
    
    if not utilisateurs:
        print("⚠️  Aucun utilisateur actif")
        return
    
    # Récupération des nouvelles offres (publiées dans les 10 dernières minutes)
    nouvelles_offres = []
    
    # France Travail (on prend les critères du premier utilisateur comme base)
    # En production : regrouper les critères similaires pour optimiser les appels API
    for utilisateur in utilisateurs:
        offres_ft = get_offres_recentes(utilisateur["criteres"], depuis_minutes=10)
        nouvelles_offres.extend(offres_ft)
    
    # ATS publics (indépendant des critères, on prend tout)
    offres_ats = scraper_tous_ats()
    nouvelles_offres.extend(offres_ats)
    
    # Déduplication
    ids_vus = set()
    offres_uniques = []
    for offre in nouvelles_offres:
        if offre["id"] not in ids_vus:
            ids_vus.add(offre["id"])
            offres_uniques.append(offre)
    
    print(f"\n📥 {len(offres_uniques)} offres uniques à analyser")
    
    # Traitement pour chaque utilisateur
    notifications_envoyees = 0
    for utilisateur in utilisateurs:
        for offre in offres_uniques:
            if traiter_offre_pour_utilisateur(offre, utilisateur, offres_vues):
                notifications_envoyees += 1
    
    sauvegarder_offres_vues(offres_vues)
    print(f"\n✅ Cycle terminé — {notifications_envoyees} notifications envoyées")


def demarrer_surveillance():
    """Lance la surveillance en continu"""
    print("🚀 Démarrage de la surveillance JobAlert IA")
    print(f"   Intervalle : toutes les {INTERVALLE_VERIFICATION // 60} minutes")
    print(f"   Score minimum : {SCORE_MINIMUM_NOTIFICATION}%\n")
    
    while True:
        try:
            cycle_surveillance()
        except Exception as e:
            print(f"❌ Erreur dans le cycle : {e}")
        
        print(f"\n⏳ Prochain cycle dans {INTERVALLE_VERIFICATION // 60} minutes...")
        time.sleep(INTERVALLE_VERIFICATION)


# ─────────────────────────────────────────────
# EXEMPLE DE STRUCTURE UTILISATEUR
# (à créer via l'interface Lovable)
# ─────────────────────────────────────────────
EXEMPLE_UTILISATEUR = {
    "id": "user_123",
    "email": "jean.dupont@email.com",
    "cv_original": "... texte brut du CV ...",
    "profil": {
        "nom": "Jean Dupont",
        "competences": ["Python", "Django", "PostgreSQL"],
        "annees_experience": 5,
        "secteurs": ["Tech", "Startup"],
        "resume_profil": "Développeur Python Senior avec 5 ans d'expérience"
    },
    "criteres": {
        "motsCles": "développeur python",
        "commune": "75056",
        "distance": 30,
        "typeContrat": "CDI",
        "nbResultats": 50
    },
    "score_minimum": 70,
    "actif": True
}


if __name__ == "__main__":
    # Crée un fichier utilisateurs de test si inexistant
    import os
    if not os.path.exists("utilisateurs.json"):
        with open("utilisateurs.json", "w", encoding="utf-8") as f:
            json.dump([EXEMPLE_UTILISATEUR], f, ensure_ascii=False, indent=2)
        print("✅ Fichier utilisateurs créé avec un exemple")
    
    # Lance la surveillance
    demarrer_surveillance()
