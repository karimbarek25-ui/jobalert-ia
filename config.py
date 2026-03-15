"""
Configuration centralisée : limites, timeouts, sécurité.
Tout est modifiable via variables d'environnement pour rester maître du coût et du risque.
"""
import os

# ─── Limites anti-abus et coût ───
MAX_PDF_BYTES = int(os.environ.get("MAX_PDF_BYTES", "10")) * 1024 * 1024  # 10 Mo par défaut
MAX_CV_TEXT_CHARS = int(os.environ.get("MAX_CV_TEXT_CHARS", "150000"))  # ~150k caractères
MAX_JSON_BODY_BYTES = int(os.environ.get("MAX_JSON_BODY_BYTES", "500000"))  # 500 Ko body max
MAX_OFFRES_RESULTS = min(int(os.environ.get("MAX_OFFRES_RESULTS", "50")), 100)  # cap 100
REQUEST_TIMEOUT_SEC = int(os.environ.get("REQUEST_TIMEOUT_SEC", "30"))
OPENAI_TIMEOUT_SEC = int(os.environ.get("OPENAI_TIMEOUT_SEC", "60"))

# ─── Rate limiting (requêtes / fenêtre) ───
RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "60"))  # par fenêtre
RATE_LIMIT_WINDOW_SEC = int(os.environ.get("RATE_LIMIT_WINDOW_SEC", "60"))
RATE_LIMIT_IA_REQUESTS = int(os.environ.get("RATE_LIMIT_IA_REQUESTS", "20"))  # routes IA (coûteuses)
RATE_LIMIT_IA_WINDOW_SEC = int(os.environ.get("RATE_LIMIT_IA_WINDOW_SEC", "60"))

# ─── Cache léger (réduire coût OpenAI / API) ───
CACHE_OFFRES_TTL_SEC = int(os.environ.get("CACHE_OFFRES_TTL_SEC", "120"))  # 2 min
CACHE_SCORER_TTL_SEC = int(os.environ.get("CACHE_SCORER_TTL_SEC", "300"))  # 5 min
