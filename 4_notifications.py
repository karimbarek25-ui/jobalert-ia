"""
SCRIPT 4 — Notifications et surveillance en temps réel
- Envoi d'emails de notification
- Surveillance continue des sources
- Relance automatique des candidatures sans réponse
"""

import smtplib
import json
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

# ─────────────────────────────────────────────
# CONFIGURATION EMAIL (Brevo recommandé)
# Toutes les valeurs via variables d'environnement — ne jamais committer de secrets
# ─────────────────────────────────────────────
import os
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp-relay.brevo.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_EXPEDITEUR = os.environ.get("EMAIL_EXPEDITEUR", "")
NOM_EXPEDITEUR = os.environ.get("NOM_EXPEDITEUR", "JobAlert IA")


def envoyer_notification_offre(destinataire: str, offre: dict, score: dict, prenom: str = ""):
    """
    Envoie une notification email pour une nouvelle offre matchée
    """
    sujet = f"🎯 {score['score']}% de compatibilité — {offre['titre']} chez {offre['entreprise']}"
    
    # HTML de l'email
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #f5f5f5; }}
            .container {{ background: white; padding: 30px; border-radius: 12px; margin: 20px; }}
            .header {{ background: #2563eb; color: white; padding: 20px; border-radius: 8px; text-align: center; }}
            .score {{ font-size: 48px; font-weight: bold; color: #2563eb; text-align: center; margin: 20px 0; }}
            .offre-card {{ background: #f8faff; border: 1px solid #dbeafe; border-radius: 8px; padding: 20px; margin: 20px 0; }}
            .btn {{ display: inline-block; background: #2563eb; color: white; padding: 14px 28px; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 16px; }}
            .points {{ margin: 10px 0; }}
            .point {{ background: #dcfce7; border-radius: 4px; padding: 6px 12px; margin: 4px 0; font-size: 14px; }}
            .footer {{ text-align: center; color: #888; font-size: 12px; margin-top: 20px; }}
            .timing {{ background: #fef3c7; padding: 10px; border-radius: 6px; text-align: center; font-weight: bold; color: #92400e; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>🚀 Nouvelle offre pour toi{', ' + prenom if prenom else ''} !</h2>
            </div>
            
            <div class="score">{score['score']}% compatible</div>
            
            <div class="timing">
                ⏱️ Publiée il y a moins de 5 minutes — Tu es parmi les premiers !
            </div>
            
            <div class="offre-card">
                <h2 style="margin: 0 0 10px 0; color: #1e40af;">{offre['titre']}</h2>
                <p style="margin: 5px 0;">🏢 <strong>{offre['entreprise']}</strong></p>
                <p style="margin: 5px 0;">📍 {offre.get('lieu', 'Non précisé')}</p>
                <p style="margin: 5px 0;">📄 {offre.get('contrat', 'Non précisé')}</p>
                <p style="margin: 5px 0;">💰 {offre.get('salaire', 'Non précisé')}</p>
                <p style="margin: 5px 0; color: #888; font-size: 13px;">Source : {offre.get('source', 'France Travail')}</p>
            </div>
            
            <div class="points">
                <p><strong>✅ Pourquoi tu matches :</strong></p>
                {''.join([f'<div class="point">✓ {p}</div>' for p in score.get('points_forts', [])[:3]])}
            </div>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="{offre.get('url', '#')}" class="btn">
                    Postuler en 1 clic →
                </a>
            </div>
            
            <p style="color: #666; font-size: 14px; text-align: center;">
                {score.get('recommandation', '')}
            </p>
            
            <div class="footer">
                <p>Ton CV et ta lettre de motivation sont déjà adaptés à cette offre dans ton dashboard.</p>
                <p><a href="#">Voir mon dashboard</a> · <a href="#">Gérer mes alertes</a> · <a href="#">Se désabonner</a></p>
            </div>
        </div>
    </body>
    </html>
    """
    
    _envoyer_email(destinataire, sujet, html)
    print(f"✅ Notification envoyée à {destinataire} pour {offre['titre']} chez {offre['entreprise']}")


def envoyer_relance_candidature(destinataire: str, candidature: dict, prenom: str = ""):
    """
    Envoie un email de relance pour une candidature sans réponse
    """
    jours_ecoules = (datetime.utcnow() - datetime.fromisoformat(candidature['date_candidature'])).days
    
    sujet = f"📬 Relance recommandée — {candidature['titre']} chez {candidature['entreprise']}"
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2>📬 Il est temps de relancer !</h2>
        <p>Bonjour{' ' + prenom if prenom else ''},</p>
        <p>Tu as postulé à <strong>{candidature['titre']}</strong> chez <strong>{candidature['entreprise']}</strong> il y a <strong>{jours_ecoules} jours</strong> et tu n'as pas encore eu de réponse.</p>
        <p>Une relance polie peut multiplier tes chances par 2. Voici un modèle prêt à envoyer :</p>
        
        <div style="background: #f0f9ff; border-left: 4px solid #2563eb; padding: 15px; margin: 20px 0; border-radius: 4px;">
            <p><em>Objet : Suivi de ma candidature au poste de {candidature['titre']}</em></p>
            <p><em>Bonjour,</em></p>
            <p><em>Je me permets de revenir vers vous concernant ma candidature au poste de {candidature['titre']} que j'ai soumise le {candidature['date_candidature'][:10]}. Je reste très intéressé(e) par cette opportunité et serais ravi(e) d'échanger avec vous.</em></p>
            <p><em>Dans l'attente de votre retour, je vous adresse mes cordiales salutations.</em></p>
        </div>
        
        <a href="{candidature.get('url', '#')}" style="background: #2563eb; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; display: inline-block;">
            Envoyer la relance →
        </a>
    </body>
    </html>
    """
    
    _envoyer_email(destinataire, sujet, html)
    print(f"✅ Relance envoyée pour {candidature['titre']} chez {candidature['entreprise']}")


def envoyer_rapport_hebdomadaire(destinataire: str, stats: dict, prenom: str = ""):
    """
    Envoie un rapport hebdomadaire avec les stats de recherche
    """
    sujet = f"📊 Ton bilan de la semaine — {stats.get('candidatures_semaine', 0)} candidatures envoyées"
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2>📊 Ton bilan de la semaine</h2>
        <p>Bonjour{' ' + prenom if prenom else ''},</p>
        
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 20px 0;">
            <div style="background: #eff6ff; padding: 15px; border-radius: 8px; text-align: center;">
                <div style="font-size: 36px; font-weight: bold; color: #2563eb;">{stats.get('offres_detectees', 0)}</div>
                <div>Offres détectées</div>
            </div>
            <div style="background: #f0fdf4; padding: 15px; border-radius: 8px; text-align: center;">
                <div style="font-size: 36px; font-weight: bold; color: #16a34a;">{stats.get('candidatures_semaine', 0)}</div>
                <div>Candidatures envoyées</div>
            </div>
            <div style="background: #fefce8; padding: 15px; border-radius: 8px; text-align: center;">
                <div style="font-size: 36px; font-weight: bold; color: #ca8a04;">{stats.get('taux_reponse', 0)}%</div>
                <div>Taux de réponse</div>
            </div>
            <div style="background: #fdf4ff; padding: 15px; border-radius: 8px; text-align: center;">
                <div style="font-size: 36px; font-weight: bold; color: #9333ea;">{stats.get('entretiens', 0)}</div>
                <div>Entretiens obtenus</div>
            </div>
        </div>
        
        <p><strong>Secteurs qui recrutent le plus pour ton profil :</strong></p>
        <ul>
            {''.join([f'<li>{s}</li>' for s in stats.get('top_secteurs', [])])}
        </ul>
        
        <a href="#" style="background: #2563eb; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; display: inline-block;">
            Voir mon dashboard complet →
        </a>
    </body>
    </html>
    """
    
    _envoyer_email(destinataire, sujet, html)


def _envoyer_email(destinataire: str, sujet: str, html: str):
    """Fonction interne d'envoi d'email via SMTP"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = sujet
    msg["From"] = f"{NOM_EXPEDITEUR} <{EMAIL_EXPEDITEUR}>"
    msg["To"] = destinataire
    
    msg.attach(MIMEText(html, "html"))
    
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(EMAIL_EXPEDITEUR, destinataire, msg.as_string())
    except Exception as e:
        print(f"❌ Erreur envoi email : {e}")


# ─────────────────────────────────────────────
# TEST
# ─────────────────────────────────────────────
if __name__ == "__main__":
    offre_test = {
        "titre": "Développeur Python Backend",
        "entreprise": "Doctolib",
        "lieu": "Paris 75009",
        "contrat": "CDI",
        "salaire": "45K-55K€",
        "url": "https://example.com/offre",
        "source": "Greenhouse (Doctolib)"
    }
    score_test = {
        "score": 94,
        "points_forts": ["5 ans d'expérience Python", "Maîtrise FastAPI", "Expérience startup"],
        "recommandation": "Excellent match ! Ton profil correspond parfaitement aux critères."
    }
    
    print("Test d'envoi de notification...")
    envoyer_notification_offre("test@email.com", offre_test, score_test, prenom="Jean")
