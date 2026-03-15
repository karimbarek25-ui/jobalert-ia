"""
SCRIPT 3 — Intelligence Artificielle
- Score de compatibilité offre/profil (0-100%)
- Adaptation du CV aux mots-clés de l'offre
- Génération de la lettre de motivation personnalisée
- Briefing entretien
"""

import os
import json
from openai import OpenAI

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))


def analyser_cv(texte_cv: str) -> dict:
    """
    Analyse un CV brut et extrait les informations structurées
    Retourne : compétences, expériences, secteurs, prétentions salariales
    """
    prompt = f"""
    Analyse ce CV et extrais les informations suivantes en JSON :
    
    {{
        "nom": "Prénom Nom",
        "email": "email@exemple.com",
        "telephone": "0X XX XX XX XX",
        "competences": ["compétence1", "compétence2"],
        "experiences": [
            {{
                "poste": "Titre du poste",
                "entreprise": "Nom entreprise",
                "duree": "2021-2023",
                "description": "Résumé des missions"
            }}
        ],
        "formations": ["Formation 1", "Formation 2"],
        "secteurs": ["secteur1", "secteur2"],
        "langues": ["Français", "Anglais"],
        "annees_experience": 5,
        "pretention_salariale_min": 35000,
        "pretention_salariale_max": 45000,
        "localisation": "Paris",
        "resume_profil": "Résumé en 2 phrases du profil"
    }}
    
    CV à analyser :
    {texte_cv}
    
    Réponds UNIQUEMENT avec le JSON, sans texte avant ou après.
    """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1
    )
    
    try:
        contenu = response.choices[0].message.content
        contenu = contenu.strip()
        if "```" in contenu:
            contenu = contenu.split("```")[1]
            if contenu.startswith("json"):
                contenu = contenu[4:]
        profil = json.loads(contenu)

        print(f"✅ CV analysé : {profil.get('nom')} —    	{profil.get('annees_experience')} ans d'expérience")
        return profil
    except:
        print("⚠️  Erreur parsing JSON du CV")
        return {}


def scorer_compatibilite(profil: dict, offre: dict) -> dict:
    """
    Calcule un score de compatibilité entre un profil et une offre
    Retourne le score (0-100) et les raisons
    """
    prompt = f"""
    Tu es un expert en recrutement. Évalue la compatibilité entre ce candidat et cette offre d'emploi.
    
    PROFIL CANDIDAT :
    {json.dumps(profil, ensure_ascii=False, indent=2)}
    
    OFFRE D'EMPLOI :
    Titre : {offre.get('titre')}
    Entreprise : {offre.get('entreprise')}
    Lieu : {offre.get('lieu')}
    Description : {offre.get('description', '')[:1000]}
    Compétences requises : {', '.join(offre.get('competences', []))}
    
    Réponds en JSON :
    {{
        "score": 87,
        "points_forts": ["raison1", "raison2", "raison3"],
        "points_faibles": ["manque1", "manque2"],
        "recommandation": "Phrase expliquant pourquoi postuler ou non",
        "mots_cles_manquants": ["mot1", "mot2"]
    }}
    
    Réponds UNIQUEMENT avec le JSON.
    """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1
    )
    
    try:
        contenu = response.choices[0].message.content
        contenu = contenu.strip()
        if "```" in contenu:
            contenu = contenu.split("```")[1]
            if contenu.startswith("json"):
                contenu = contenu[4:]
        resultat = json.loads(contenu)
        print(f"✅ Score calculé : {resultat.get('score')}% pour {offre.get('titre')} chez {offre.get('entreprise')}")
        return resultat
    except:
        return {"score": 0, "points_forts": [], "points_faibles": [], "recommandation": "Erreur d'analyse"}


def adapter_cv(profil: dict, offre: dict, cv_original: str) -> str:
    """
    Réécrit le CV pour maximiser la compatibilité avec l'offre
    Adapte les mots-clés, réorganise les priorités
    """
    prompt = f"""
    Tu es un expert en rédaction de CV. Adapte ce CV pour maximiser les chances pour cette offre d'emploi.
    
    OFFRE CIBLÉE :
    Titre : {offre.get('titre')}
    Entreprise : {offre.get('entreprise')}
    Description : {offre.get('description', '')[:800]}
    Compétences requises : {', '.join(offre.get('competences', []))}
    
    CV ORIGINAL :
    {cv_original}
    
    INSTRUCTIONS :
    1. Réorganise les compétences pour mettre en avant celles qui correspondent à l'offre
    2. Adapte le résumé professionnel pour coller au poste visé
    3. Mets en valeur les expériences les plus pertinentes
    4. Intègre naturellement les mots-clés de l'offre
    5. Ne mens pas — utilise uniquement ce qui est dans le CV original
    6. Garde un format professionnel et clair
    
    Retourne le CV adapté en texte formaté, prêt à être mis en page.
    """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    
    cv_adapte = response.choices[0].message.content
    print(f"✅ CV adapté pour : {offre.get('titre')} chez {offre.get('entreprise')}")
    return cv_adapte


def generer_lettre_motivation(profil: dict, offre: dict) -> str:
    """
    Génère une lettre de motivation personnalisée
    Mentionne l'entreprise, le poste, et l'actualité de la boîte si possible
    """
    prompt = f"""
    Tu es un expert en recherche d'emploi. Rédige une lettre de motivation percutante et personnalisée.
    
    PROFIL CANDIDAT :
    Nom : {profil.get('nom')}
    Résumé : {profil.get('resume_profil')}
    Compétences clés : {', '.join(profil.get('competences', [])[:8])}
    Années d'expérience : {profil.get('annees_experience')}
    
    OFFRE CIBLÉE :
    Titre : {offre.get('titre')}
    Entreprise : {offre.get('entreprise')}
    Lieu : {offre.get('lieu')}
    Description : {offre.get('description', '')[:800]}
    
    INSTRUCTIONS :
    1. Commence par une accroche originale qui mentionne l'entreprise spécifiquement
    2. Montre que tu connais l'entreprise et ses valeurs
    3. Fais le lien entre tes compétences et les besoins du poste
    4. Sois concis (3 paragraphes maximum)
    5. Termine par une phrase de clôture professionnelle
    6. Ton : professionnel mais humain, pas trop formel
    7. Longueur : 250-350 mots
    
    Format de sortie : La lettre directement, sans "Objet :" ni en-tête.
    """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    
    lettre = response.choices[0].message.content
    print(f"✅ Lettre générée pour : {offre.get('titre')} chez {offre.get('entreprise')}")
    return lettre


def preparer_briefing_entretien(profil: dict, offre: dict) -> dict:
    """
    Prépare un briefing complet pour l'entretien
    Questions probables, points à mettre en avant, recherches sur l'entreprise
    """
    prompt = f"""
    Prépare un briefing d'entretien complet pour ce candidat et cette offre.
    
    PROFIL : {json.dumps(profil, ensure_ascii=False)}
    OFFRE : Titre: {offre.get('titre')}, Entreprise: {offre.get('entreprise')}, Description: {offre.get('description', '')[:600]}
    
    Réponds en JSON :
    {{
        "questions_probables": [
            {{"question": "...", "conseil_reponse": "..."}}
        ],
        "points_a_mettre_en_avant": ["point1", "point2"],
        "questions_a_poser": ["question1", "question2"],
        "recherches_entreprise": ["fait1 sur l'entreprise", "fait2"],
        "pieges_a_eviter": ["piege1", "piege2"]
    }}
    
    Réponds UNIQUEMENT avec le JSON.
    """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )
    
    try:
        briefing = json.loads(response.choices[0].message.content)
        print(f"✅ Briefing entretien généré pour : {offre.get('titre')}")
        return briefing
    except:
        return {}


# ─────────────────────────────────────────────
# TEST
# ─────────────────────────────────────────────
if __name__ == "__main__":
    # Exemple de test
    cv_test = """
    Jean Dupont - jean.dupont@email.com - 06 12 34 56 78
    Développeur Python Senior - 5 ans d'expérience
    
    COMPÉTENCES : Python, Django, FastAPI, PostgreSQL, Docker, AWS, Git
    
    EXPÉRIENCES :
    - Développeur Backend Senior @ Startup Paris (2021-2024)
      Développement d'APIs REST, microservices, optimisation BDD
    - Développeur Python @ Agence Web (2019-2021)
      Sites web Django, intégrations API tierces
    
    FORMATION : Master Informatique - Université Paris (2019)
    LANGUES : Français (natif), Anglais (courant)
    """
    
    offre_test = {
        "titre": "Développeur Python Backend",
        "entreprise": "Doctolib",
        "lieu": "Paris",
        "description": "Rejoignez notre équipe technique pour développer nos APIs de santé. Stack : Python, FastAPI, PostgreSQL, AWS.",
        "competences": ["Python", "FastAPI", "PostgreSQL", "AWS"]
    }
    
    print("1️⃣  Analyse du CV...")
    profil = analyser_cv(cv_test)
    
    print("\n2️⃣  Calcul du score de compatibilité...")
    score = scorer_compatibilite(profil, offre_test)
    print(f"   Score : {score['score']}%")
    print(f"   Points forts : {score['points_forts']}")
    
    print("\n3️⃣  Génération de la lettre...")
    lettre = generer_lettre_motivation(profil, offre_test)
    print(f"\n{lettre[:300]}...")
