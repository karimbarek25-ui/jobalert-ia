# JobAlert IA — API

API FastAPI pour JobAlert by KB : offres (France Travail + ATS), scoring IA, lettres de motivation, candidatures.

- **Sans config base** : si `SUPABASE_SERVICE_KEY` n’est pas défini, candidatures et profils sont stockés en fichiers JSON. Aucune action requise.
- **Déploiement** : voir [DEPLOIEMENT.md](DEPLOIEMENT.md) (Railway, variables, optionnel Supabase / Stripe).
- **Contexte produit** : voir [CONTEXTE_PROJET.md](CONTEXTE_PROJET.md).
- **Propriété** : voir [PROPRIETAIRE.md](PROPRIETAIRE.md).

```bash
pip install -r requirements.txt
# Créer .env avec au minimum : SUPABASE_JWT_SECRET, SUPABASE_URL, OPENAI_API_KEY, CLIENT_ID, CLIENT_SECRET
uvicorn main:app --reload --port 8000
```

Route de santé : `GET /health` (indique si le stockage est `supabase` ou `json`).
