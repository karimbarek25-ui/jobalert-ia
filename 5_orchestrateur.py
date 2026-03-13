"""
SCRIPT 5 — Orchestrateur principal
Lance la surveillance en continu et coordonne tous les scripts.
Stockage : Supabase (table user_data + offres_vues)
"""

import os
import time
import hashlib
import requests
from datetime import datetime

import importlib.util, sys, pathlib

def _load(short, full_name):
    p = pathlib.Path(__file__).parent / full_name
    spec = importlib.util.spec_from_file_location(short, p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[short] = mod
    spec.loader.exec_module(mod)
    return mod

_ft   = _load("france_travail", "1_france_travail.py")
_ats  = _load("ats_scraper",    "2_ats_scraper.py")
_ia   = _load("ia_engine",      "3_ia_engine.py")
_notif= _load("notifications",  "4_notifications.py")

rechercher_offres           = _ft.rechercher_offres
get_offres_recentes         = _ft.get_offres_recentes
scraper_tous_ats            = _ats.scraper_tous_ats
analyser_cv                 = _ia.analyser_cv
scorer_compatibilite        = _ia.scorer_compatibilite
adapter_cv                  = _ia.adapter_cv
generer_lettre_motivation   = _ia.generer_lettre_motivation
envoyer_notification_offre  = _notif.envoyer_notification_offre

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
INTERVALLE_VERIFICATION  = 5 * 60  # toutes les 5 minutes
SCORE_MINIMUM_NOTIFICATION = 70    # notifier uniquement si score >= 70%

SUPABASE_URL      = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")


# ─────────────────────────────────────────────
# HELPERS SUPABASE
# ─────────────────────────────────────────────

def _sb_headers(service_role: bool = False) -> dict:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", SUPABASE_ANON_KEY)
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _sb_get(path: str, params: str = "") -> list:
    """GET simple vers l'API REST Supabase. Retourne une liste ou []."""
    if not SUPABASE_URL:
        return []
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    if params:
        url += f"?{params}"
    try:
        r = requests.get(url, headers=_sb_headers(), timeout=10)
        return r.json() if r.ok else []
    except Exception as e:
        print(f"[Supabase GET /{path}] Erreur: {e}")
        return []


def _sb_post(path: str, payload, prefer: str = "return=minimal"):
    """POST/upsert vers l'API REST Supabase."""
    if not SUPABASE_URL:
        return
    try:
        h = {**_sb_headers(), "Prefer": prefer}
        requests.post(
            f"{SUPABASE_URL}/rest/v1/{path}",
            headers=h, json=payload, timeout=10
        )
    except Exception as e:
        print(f"[Supabase POST /{path}] Erreur: {e}")


def _sb_patch(path: str, filter_qs: str, payload: dict):
    """PATCH vers l'API REST Supabase."""
    if not SUPABASE_URL:
        return
    try:
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/{path}?{filter_qs}",
            headers={**_sb_headers(), "Prefer": "return=minimal"},
            json=payload, timeout=10
        )
    except Exception as e:
        print(f"[Supabase PATCH /{path}] Erreur: {e}")


# ─────────────────────────────────────────────
# COUCHE DONNÉES — Supabase
# ─────────────────────────────────────────────

def charger_utilisateurs() -> list:
    """Retourne tous les utilisateurs ayant une alerte email active."""
    rows = _sb_get("user_data", "select=user_id,data")
    utilisateurs = []
    for row in rows:
        data   = row.get("data", {})
        alerte = data.get("alerte_email", {})
        if not alerte.get("active"):
            continue
        utilisateurs.append({
            "id":          row["user_id"],
            "email":       alerte.get("email", ""),
            "cv_original": data.get("cv_texte", ""),
            "profil":      data.get("profil", {}),
            "criteres": {
                "motsCles":    alerte.get("poste", ""),
                "commune":     alerte.get("ville", ""),
                "typeContrat": alerte.get("contrat", ""),
            },
            "score_minimum": alerte.get("score_min", SCORE_MINIMUM_NOTIFICATION),
            "actif": True,
        })
    return utilisateurs


def charger_offres_vues() -> set:
    """Retourne l'ensemble des clés offre+user déjà traitées."""
    rows = _sb_get("offres_vues", "select=offre_key")
    return {row["offre_key"] for row in rows}


def sauvegarder_offres_vues(nouvelles_cles: set):
    """Insère en masse les nouvelles clés (ignore les doublons via UNIQUE)."""
    if not nouvelles_cles:
        return
    _sb_post(
        "offres_vues",
        [{"offre_key": k} for k in nouvelles_cles],
        prefer="resolution=ignore-duplicates,return=minimal",
    )


def sauvegarder_candidature(
    utilisateur_id: str, offre: dict, score: dict, cv_adapte: str, lettre: str
):
    """Ajoute une candidature dans user_data.data.candidatures."""
    rows = _sb_get("user_data", f"user_id=eq.{utilisateur_id}&select=data")
    if not rows:
        return
    data         = rows[0].get("data", {})
    candidatures = data.setdefault("candidatures", [])

    offre_id = offre.get("id", "")
    if any(c.get("offre_id") == offre_id for c in candidatures):
        return  # déjà présente

    now = datetime.utcnow().isoformat()
    candidatures.append({
        "id":       hashlib.md5(f"{offre_id}{utilisateur_id}".encode()).hexdigest(),
        "offre_id": offre_id,
        "offre":    offre,
        "score":    score,
        "cv_adapte": cv_adapte,
        "lettre":   lettre,
        "statut":   "prête",
        "cree_le":  now,
        "maj_le":   now,
    })

    _sb_patch("user_data", f"user_id=eq.{utilisateur_id}", {"data": data})


# ─────────────────────────────────────────────
# BOUCLE PRINCIPALE DE SURVEILLANCE
# ─────────────────────────────────────────────

def traiter_offre_pour_utilisateur(
    offre: dict, utilisateur: dict, offres_vues: set, nouvelles_cles: set
) -> bool:
    """
    Traite une offre pour un utilisateur.
    Retourne True si une notification a été envoyée.
    """
    cle = f"{offre['id']}_{utilisateur['id']}"
    if cle in offres_vues:
        return False

    nouvelles_cles.add(cle)
    offres_vues.add(cle)

    score = scorer_compatibilite(utilisateur["profil"], offre)
    if score["score"] < utilisateur.get("score_minimum", SCORE_MINIMUM_NOTIFICATION):
        return False

    print(f"\n🎯 Match ! {score['score']}% — {offre['titre']} chez {offre['entreprise']}")

    cv_adapte = adapter_cv(utilisateur["profil"], offre, utilisateur["cv_original"])
    lettre    = generer_lettre_motivation(utilisateur["profil"], offre)

    sauvegarder_candidature(utilisateur["id"], offre, score, cv_adapte, lettre)

    envoyer_notification_offre(
        utilisateur["email"],
        offre,
        score,
        prenom=utilisateur["profil"].get("nom", "").split()[0] if utilisateur["profil"].get("nom") else "",
    )
    return True


def cycle_surveillance():
    print(f"\n{'='*50}")
    print(f"🔍 Cycle de surveillance — {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*50}")

    utilisateurs = charger_utilisateurs()
    if not utilisateurs:
        print("⚠️  Aucun utilisateur actif")
        return

    offres_vues    = charger_offres_vues()
    nouvelles_cles: set = set()

    nouvelles_offres = []
    for utilisateur in utilisateurs:
        offres_ft = get_offres_recentes(utilisateur["criteres"], depuis_minutes=10)
        nouvelles_offres.extend(offres_ft)

    offres_ats = scraper_tous_ats()
    nouvelles_offres.extend(offres_ats)

    # Déduplication
    ids_vus, offres_uniques = set(), []
    for o in nouvelles_offres:
        if o["id"] not in ids_vus:
            ids_vus.add(o["id"])
            offres_uniques.append(o)

    print(f"\n📥 {len(offres_uniques)} offres uniques à analyser")

    notifications = 0
    for utilisateur in utilisateurs:
        for o in offres_uniques:
            if traiter_offre_pour_utilisateur(o, utilisateur, offres_vues, nouvelles_cles):
                notifications += 1

    sauvegarder_offres_vues(nouvelles_cles)
    print(f"\n✅ Cycle terminé — {notifications} notifications envoyées")


def demarrer_surveillance():
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


if __name__ == "__main__":
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        print("❌ SUPABASE_URL et SUPABASE_ANON_KEY sont requis (variables d'environnement)")
    else:
        demarrer_surveillance()
