# JobAlert by KB — Contexte projet complet

## Vue d'ensemble
Application SaaS de veille emploi automatisée.
- **Vitrine marketing** : jobalertkb.fr (WordPress)
- **App SaaS** : jobalertkb.fr/app (HTML/CSS/JS vanilla, fichier unique : app/index.html)

## Hébergement & accès
- Hébergeur : OVH
- Domaine : jobalertkb.fr
- FTP : à configurer en variables d'environnement ou coffre-fort (ne jamais committer les identifiants).

## Stack WordPress (vitrine)
- Thème actif : **Twenty Twenty-Five Child** (twentytwentyfive-child)
- Fichiers clés sur le FTP :
  - `/www/wp-content/themes/twentytwentyfive-child/style.css` → CSS complet du site vitrine
  - `/www/wp-content/themes/twentytwentyfive-child/functions.php` → hooks WP, fonts, logo JS, FAQ accordion, endpoint Stripe
- Police : **Manrope** (Google Fonts, 400;500;600;700;800)
- Page d'accueil : post ID 5

### Méthode de déploiement PHP
Pour mettre à jour le contenu WordPress : script PHP uploadé via FTP, exécuté via URL avec paramètre secret, puis le script se supprime (`@unlink(__FILE__)`).  
**Ne jamais committer le secret en clair** — utiliser une variable d'environnement côté serveur ou un secret stocké de façon sécurisée.

---

## Design system vitrine (CSS)
- Thème : dark
- Couleurs : `--bg: #07070f`, `--bg2: #0d0d1a`, `--blue: #2563eb`, `--blue-l: #60a5fa`, `--green: #10b981`, `--text: #f1f5f9`, `--muted: #94a3b8`, `--border: rgba(255,255,255,0.08)`, `--radius: 14px`
- Classes : `.ja-hero`, `.ja-section`, `.ja-features`, `.ja-pricing`, `.ja-faq`, `.ja-btn`, etc.
- Mobile : `html, body { overflow-x: hidden; }`, `*, *::before, *::after { min-width: 0; }`, pseudo-éléments avec `min()` pour éviter le débordement.

---

## App SaaS (/app/index.html)
- Fichier unique : `/www/app/index.html`
- Design : `--bg: #0a0a0a`, `--surface: #111111`, `--surface2: #181818`, `--text: #f0f0f0`, `--blue: #3b82f6`
- UI : sidebar (desktop), dashboard offres, modal candidature, bottom nav mobile (≤900px), responsive

## Backend / API
- **Stripe** : endpoint REST WordPress `/jakb/v1/checkout` (functions.php)
- **Auth** : WordPress (wp_nonce, rôles) pour la vitrine ; Supabase pour l’app SaaS (JWT)
- **API métier** : FastAPI (ce repo) — offres, scoring IA, CV, lettres

---

## État actuel
- Vitrine : redesign en cours (dark theme, gradient bleu→vert)
- App : UI prête ; fonctionnalités métier (scraping, alertes email, matching IA) en cours / à connecter au backend FastAPI

---

## Roadmap fonctionnelle

| # | Fonctionnalité | Statut actuel (backend jobalert-ia) |
|---|----------------|--------------------------------------|
| 1 | Agrégation offres (60+ sources : France Travail, LinkedIn, Indeed, APEC, WTTJ, Lever, Greenhouse, Workday, Ashby…) | Partiel : France Travail + quelques ATS (Lever, Greenhouse) |
| 2 | Alertes email &lt; 5 min après publication | Script orchestrateur (4_notifications.py) existant, à brancher sur une base et un cron |
| 3 | Score IA matching (CV ↔ fiche de poste) | ✅ API `/ia/scorer` |
| 4 | Lettre de motivation IA (CV + fiche) | ✅ API `/ia/lettre` et `/ia/package-complet` |
| 5 | Suivi des candidatures (dashboard) | Routes `/candidatures/{user_id}` et `/stats/{user_id}` ; stockage actuel en JSON → à migrer vers Supabase |
| 6 | Plans Gratuit vs Premium (3 candidatures/jour vs illimité + IA) | À implémenter : vérification abonnement Stripe ↔ user_id Supabase |

---

## Tarification
- **Gratuit** : 0 €/mois — alertes illimitées, 3 candidatures/jour, score IA de base
- **Premium** : 5,99 €/mois — candidatures illimitées, lettre IA, offres exclusives, score IA détaillé
- Paiement : Stripe (sans engagement, résiliable)

---

## Sécurité & propriété
- Tous les secrets (FTP, Stripe, Supabase JWT secret, France Travail, secret scripts PHP) doivent rester hors dépôt (env, coffre-fort).
- CORS API : restreindre aux origines réelles (ex. `https://jobalertkb.fr`, `https://www.jobalertkb.fr`).
- Vérifier côté API que `user_id` dans les routes correspond toujours au JWT (pas d’accès aux données d’un autre utilisateur).
