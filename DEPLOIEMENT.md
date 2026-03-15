# JobAlert by KB — Déploiement (sans rien faire à la main si tu veux)

L’API fonctionne **sans configuration** : si tu ne configures pas Supabase, les candidatures et les profils sont stockés en **fichiers JSON** sur le serveur. Aucune action obligatoire de ta part pour faire tourner le projet.

Quand tu voudras passer en production « propre », tu pourras suivre les étapes ci‑dessous (copier-coller uniquement).

---

## 1. Lancer l’API en local (aucune config requise)

```bash
cd jobalert-ia
pip install -r requirements.txt
```

Crée un fichier `.env` à la racine avec **au minimum** (pour que l’auth et les offres marchent) :

- `SUPABASE_JWT_SECRET` = clé JWT de ton projet Supabase (Auth → JWT)
- `SUPABASE_URL` = https://xxx.supabase.co
- `OPENAI_API_KEY` = ta clé OpenAI
- `CLIENT_ID` et `CLIENT_SECRET` = France Travail (partenaire)

Tu peux **ne pas** mettre `SUPABASE_SERVICE_KEY` : dans ce cas, candidatures et profils sont enregistrés en JSON (fichiers `candidatures_<user_id>.json` et `profiles.json`).

Puis :

```bash
uvicorn main:app --reload --port 8000
```

L’API est dispo sur http://localhost:8000. Route de santé : http://localhost:8000/health (indique si le stockage est `supabase` ou `json`).

---

## 2. Déployer sur Railway (copier-coller des variables)

1. Va sur [railway.app](https://railway.app), connecte-toi, **New Project** → **Deploy from GitHub** → choisis le repo **jobalert-ia**.
2. Une fois le déploiement créé, ouvre le projet → **Variables** (onglet).
3. Copie-colle **chaque ligne** ci‑dessous (en remplaçant les `xxx` par tes vraies valeurs). Railway ajoute une variable par ligne.

```
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_JWT_SECRET=xxx
SUPABASE_SERVICE_KEY=xxx
OPENAI_API_KEY=sk-xxx
CLIENT_ID=xxx
CLIENT_SECRET=xxx
CORS_ORIGINS=https://jobalertkb.fr,https://www.jobalertkb.fr
LIMIT_CANDIDATURES_FREE=3
```

Optionnel (pour passer un utilisateur en Premium depuis WordPress) :

```
INTERNAL_SECRET=choisis_une_longue_phrase_secrete
```

Optionnel (webhook Stripe) :

```
STRIPE_WEBHOOK_SECRET=whsec_xxx
```

4. Sauvegarde. Railway redéploie tout seul. L’URL de l’API s’affiche dans l’onglet **Settings** (ex. `https://jobalert-ia-production.up.railway.app`).

**Si tu ne mets pas `SUPABASE_SERVICE_KEY`** : l’API tourne quand même et utilise le stockage JSON (candidatures et profils en fichiers). Tu pourras ajouter Supabase plus tard.

---

## 3. Supabase (optionnel — seulement si tu veux une vraie base)

1. Va sur [supabase.com](https://supabase.com) → ton projet.
2. **SQL Editor** → **New query**.
3. Ouvre le fichier `supabase_schema.sql` dans ce repo, copie tout son contenu, colle dans l’éditeur, puis **Run**.
4. Dans **Settings** → **API** : note l’**URL** et la clé **service_role** (secret). Mets-les dans Railway en `SUPABASE_URL` et `SUPABASE_SERVICE_KEY`.

Après ça, l’API utilisera automatiquement Supabase pour les candidatures et les profils (plus besoin des fichiers JSON).

---

## 4. Passer un utilisateur en Premium (WordPress ou Stripe)

### Option A : depuis WordPress après le paiement Stripe

Quand un utilisateur a payé (checkout Stripe réussi côté WordPress), appelle l’API avec un secret partagé :

- **URL** : `POST https://ton-api.railway.app/internal/set-premium`
- **Header** : `X-Internal-Secret: <INTERNAL_SECRET>` (la même valeur que la variable d’env)
- **Body JSON** : `{ "user_id": "<uuid_supabase_de_l_utilisateur>", "plan": "premium" }`

Le `user_id` est l’id Supabase Auth de l’utilisateur (tu l’as côté front quand il est connecté, ou tu peux le récupérer côté WordPress si tu stockes le lien user ↔ Stripe).

**Exemple PHP (WordPress)** — à appeler après succès Stripe, avec le `user_id` que tu as stocké en session ou en metadata du checkout :

```php
$api_url = 'https://ton-api.railway.app/internal/set-premium';
$secret = getenv('JOBALERT_INTERNAL_SECRET'); // ou définir en dur de façon sécurisée
$user_id = 'uuid-supabase-de-l-utilisateur';   // à récupérer depuis ta logique checkout

$res = wp_remote_post($api_url, [
    'headers' => [
        'Content-Type' => 'application/json',
        'X-Internal-Secret' => $secret,
    ],
    'body' => json_encode(['user_id' => $user_id, 'plan' => 'premium']),
]);
```

### Option B : webhook Stripe (automatique)

1. Dans le dashboard Stripe : **Développeurs** → **Webhooks** → **Ajouter un endpoint**.
2. URL : `https://ton-api.railway.app/webhooks/stripe`.
3. Événements à écouter : `checkout.session.completed`.
4. Récupère le **Signing secret** (whsec_...) et mets-le dans Railway en `STRIPE_WEBHOOK_SECRET`.
5. Lors de la création du Checkout Session (côté WordPress/PHP), ajoute dans les metadata ou en `client_reference_id` le **user_id** Supabase du client. Ainsi, à la réception du webhook, l’API pourra mettre à jour le plan en « premium » pour ce user.

---

## 5. Résumé : ce qui est obligatoire / optionnel

| Étape | Obligatoire ? | Sans ça |
|-------|----------------|----------|
| Variables Railway (JWT, Supabase URL, OpenAI, France Travail) | Oui pour auth + offres + IA | L’API ne pourra pas authentifier ou appeler les services |
| `SUPABASE_SERVICE_KEY` | Non | Stockage en JSON (fichiers) |
| Exécuter `supabase_schema.sql` | Non (sauf si tu utilises Supabase) | Si tu mets la clé Supabase sans schéma, les tables peuvent manquer |
| `INTERNAL_SECRET` + appel set-premium depuis WordPress | Non | Tu peux passer les users en premium à la main (fichier ou Supabase) |
| Webhook Stripe | Non | Idem, mise à jour manuelle ou via set-premium |

Tu peux ne rien faire de plus que le **point 2** (Railway + variables minimales) et avoir une API qui tourne avec stockage JSON ; le reste est pour sécuriser et automatiser (Supabase, Premium, webhook).
