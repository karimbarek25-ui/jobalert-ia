# Maîtriser les coûts (sans rien céder en propriété)

Tout est configurable par **variables d’environnement** (voir `config.py` et `.env.example`). Tu gardes la main sur la facture.

## Ce qui réduit le coût sans changer de stack

- **Cache offres** : mêmes critères = même réponse pendant 2 min (pas de nouvel appel France Travail / ATS). `CACHE_OFFRES_TTL_SEC`
- **Cache scoring IA** : même profil + même offre = score en cache 5 min. Moins d’appels OpenAI. `CACHE_SCORER_TTL_SEC`
- **Rate limiting** : max 60 req/min (20 pour les routes IA). Évite les abus et les pics. `RATE_LIMIT_*`
- **Limites de taille** : PDF 10 Mo, texte CV 150k caractères, body JSON limité. Moins de tokens OpenAI. `MAX_PDF_BYTES`, `MAX_CV_TEXT_CHARS`
- **Plafond offres** : max 50 résultats par recherche (configurable, plafonné à 100). `MAX_OFFRES_RESULTS`
- **Timeouts** : requêtes HTTP et OpenAI limitées dans le temps. `REQUEST_TIMEOUT_SEC`, `OPENAI_TIMEOUT_SEC`

## Ordre de grandeur des coûts (hors ton temps)

| Service | Usage type | Coût typique |
|--------|------------|--------------|
| **Railway** | 1 API, faible trafic | Free tier ou quelques €/mois |
| **Supabase** | Auth + petite base | Free tier suffisant au début |
| **OpenAI** | gpt-4o-mini, cache activé | Quelques €/mois selon volume |
| **France Travail** | Partenaire | Gratuit (convention) |
| **Stripe** | 5,99 €/mois par client | Commission par transaction |
| **OVH** | Hébergement vitrine + app | Abonnement fixe |
| **Brevo** | Emails | Free tier puis forfait |

En restant sur des free tiers et un trafic raisonnable, tu peux garder le coût global très bas ; les variables dans `config.py` permettent d’ajuster sans toucher au code.
