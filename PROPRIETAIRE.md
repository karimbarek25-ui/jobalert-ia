# JobAlert by KB — Devenir le seul propriétaire

Ce document liste tout ce dont tu dois être le **seul détenteur** pour être propriétaire à 100 % du produit (code, hébergement, données, paiements).

## Tu restes le seul propriétaire

- **Tout le code** dans tes dépôts (jobalert-ia, jobalert-frontend, etc.) t’appartient. Aucune licence propriétaire ne te lie à un tiers pour le code métier.
- **Aucun lock-in** : tu peux migrer l’API vers un autre hébergeur (VPS, autre PaaS), changer de base (PostgreSQL ailleurs), garder le même front. Le projet n’est pas “pris en otage” par une plateforme.
- **Services utilisés** (Supabase, Stripe, OpenAI, Railway, OVH) : tu as un **compte à ton nom** et tu paies l’usage. Tu ne donnes pas la propriété du produit à ces services ; ils fournissent uniquement de l’infra et des APIs. Si tu changes de fournisseur, tu mets à jour les configs (variables d’env, clés) et le code reste le tien.
- **Données** : hébergées chez Supabase (ou en JSON sur ton serveur). Tu en gardes le contrôle (export, suppression, RGPD) via ton compte Supabase ou tes fichiers.

---

## 1. Comptes et accès

| Service | Où | À faire |
|--------|-----|--------|
| **GitHub** | github.com → dépôts (jobalert-ia, jobalert-frontend, etc.) | Compte à ton nom ; supprimer tout collaborateur ou transfert de propriété si besoin. |
| **OVH** | Hébergeur (jobalertkb.fr, FTP, fichiers /www) | Identifiants client OVH + FTP (user/pass) ; changer les mots de passe si jamais exposés. |
| **Railway** | Hébergement de l’API FastAPI | Compte Railway ; projet lié au repo ; variables d’environnement (voir ci‑dessous). |
| **Supabase** | Auth + base (profiles, candidatures) | Projet Supabase ; **URL**, **JWT secret** (Auth > JWT), **service_role key** (Settings > API). |
| **Stripe** | Paiements (Premium 5,99 €/mois) | Compte Stripe ; clés API (Dashboard > Développeurs) ; webhooks si utilisés. |
| **OpenAI** | IA (analyse CV, lettres, scoring) | Clé API sur platform.openai.com. |
| **France Travail** | API offres d’emploi | Client ID / Client secret (partenaire). |
| **Brevo** | Emails (notifications) | Compte Brevo ; identifiants SMTP (SMTP_USER / SMTP_PASSWORD). |

---

## 2. Secrets à ne jamais committer

Tout doit être en **variables d’environnement** (ou coffre-fort) :

- `SUPABASE_URL`, `SUPABASE_JWT_SECRET`, `SUPABASE_SERVICE_KEY`
- `OPENAI_API_KEY`
- `CLIENT_ID`, `CLIENT_SECRET` (France Travail)
- Clés Stripe (WordPress / PHP)
- `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_EXPEDITEUR`
- Mots de passe FTP OVH et secret des scripts PHP (ex. `?secret=...`)

Voir `.env.example` dans ce repo pour la liste côté API.

---

## 3. Où est quoi

| Élément | Emplacement |
|--------|-------------|
| Code API (FastAPI) | Repo **jobalert-ia** (ce repo) |
| Frontend app | **jobalert-frontend** et/ou OVH `/www/app/index.html` |
| Vitrine WordPress | OVH `/www/` (thème child, functions.php, endpoint Stripe) |
| Base de données (candidatures, profils) | **Supabase** (exécuter `supabase_schema.sql` si pas encore fait) |
| Déploiement API | **Railway** (build + start command dans `railway.json`) |

---

## 4. Checklist “propriétaire”

- [ ] GitHub : tu es seul owner/collaborateur sur les repos du projet.
- [ ] OVH : accès client + FTP sous ton compte ; mots de passe sécurisés.
- [ ] Railway : projet et déploiement sous ton compte ; variables d’env remplies (pas de clés dans le code).
- [ ] Supabase : projet à toi ; schéma appliqué ; JWT secret + service_role key uniquement côté serveur.
- [ ] Stripe : compte à ton nom ; clés et webhooks configurés pour jobalertkb.fr.
- [ ] France Travail : credentials partenaire sous ton nom / structure.
- [ ] Brevo (SMTP) : compte et identifiants sous ton contrôle.
- [ ] Domaine jobalertkb.fr : enregistrement et DNS sous ton nom (souvent géré dans OVH).

---

## 5. Après un changement de main

Si quelqu’un d’autre a créé les comptes (Stripe, Supabase, Railway, etc.) :

1. **Créer tes propres comptes** (même service).
2. **Migrer** : nouveau projet Supabase + export/import si besoin ; recréer le projet Railway ; reconfigurer Stripe (clés, webhooks).
3. **Mettre à jour** les variables d’environnement (Railway, WordPress, scripts PHP, .env local).
4. **Révoquer** les anciennes clés / accès sur les anciens comptes.

---

## 6. Fichiers utiles dans ce repo

- `CONTEXTE_PROJET.md` — Contexte produit, roadmap, stack.
- `.env.example` — Liste des variables d’environnement pour l’API et l’orchestrateur.
- `supabase_schema.sql` — Schéma des tables Supabase (profiles, candidatures) à exécuter dans le SQL Editor Supabase.

Tu peux garder ce fichier à jour (ajouter des services, des étapes) au fur et à mesure que le produit évolue.

---

## Performance, sécurité et coût (sans dépendre à un tiers)

Le projet est pensé pour être **performant**, **sécurisé** et **peu coûteux** tout en restant sous ton contrôle :

- **Rate limiting** : en mémoire (pas de Redis). Limite les abus et les pics de coût (OpenAI, API France Travail).
- **Cache** : offres et scoring mis en cache quelques minutes pour réduire le nombre d’appels externes (donc la facture).
- **Limites** : taille des PDF, taille des body JSON, nombre d’offres max. Tout est configurable via variables d’env (`config.py`).
- **En-têtes de sécurité** : X-Content-Type-Options, X-Frame-Options, etc. appliqués par l’API.
- **Validation stricte** : tous les modèles Pydantic limitent la taille des entrées pour éviter abus et surcoûts.

Aucune dépendance à un service “premium” pour la perf ou la sécu : tout est dans ton code et tes variables d’environnement.
