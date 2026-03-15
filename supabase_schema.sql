<<<<<<< HEAD
-- JobAlert by KB — Schéma Supabase
-- Exécuter dans l’éditeur SQL du projet Supabase (Dashboard > SQL Editor)

-- Profils utilisateur (plan gratuit / premium)
CREATE TABLE IF NOT EXISTS public.profiles (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  plan TEXT NOT NULL DEFAULT 'free' CHECK (plan IN ('free', 'premium')),
  stripe_customer_id TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Candidatures (une par offre préparée par utilisateur)
CREATE TABLE IF NOT EXISTS public.candidatures (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  offre JSONB NOT NULL,
  score JSONB NOT NULL,
  cv_adapte TEXT,
  lettre TEXT,
  statut TEXT NOT NULL DEFAULT 'prête' CHECK (statut IN ('prête', 'envoyée', 'vue', 'entretien', 'refus', 'acceptée')),
  date_preparation TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  date_candidature TIMESTAMPTZ,
  date_reponse TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_candidatures_user_id ON public.candidatures(user_id);
CREATE INDEX IF NOT EXISTS idx_candidatures_created_at ON public.candidatures(created_at);

-- RLS : chaque utilisateur ne voit que ses données
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.candidatures ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users read own profile" ON public.profiles
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Service role full access profiles" ON public.profiles
  FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Users read own candidatures" ON public.candidatures
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users insert own candidatures" ON public.candidatures
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users update own candidatures" ON public.candidatures
  FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Service role full access candidatures" ON public.candidatures
  FOR ALL USING (auth.role() = 'service_role');

-- L’API utilise la clé service_role pour insérer/lire (bypass RLS côté backend)
=======
-- ============================================================
-- JobAlert — Schéma Supabase
-- À exécuter dans : Supabase > SQL Editor
-- ============================================================

-- ── Table principale : données utilisateur ──
-- Stocke profil, critères, candidatures, favoris, alertes, CV
CREATE TABLE IF NOT EXISTS user_data (
    user_id  TEXT PRIMARY KEY,
    data     JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Mise à jour automatique du timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_user_data_updated_at ON user_data;
CREATE TRIGGER trg_user_data_updated_at
    BEFORE UPDATE ON user_data
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ── Table de déduplication : offres déjà traitées ──
-- Empêche l'orchestrateur de renotifier deux fois la même offre au même utilisateur
CREATE TABLE IF NOT EXISTS offres_vues (
    id         UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    offre_key  TEXT UNIQUE NOT NULL,  -- "{offre_id}_{user_id}"
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_offres_vues_key ON offres_vues(offre_key);

-- Nettoyage automatique des offres vues de plus de 60 jours (évite la croissance infinie)
-- À activer via pg_cron dans Supabase si disponible :
-- SELECT cron.schedule('clean-offres-vues', '0 3 * * *',
--   $$DELETE FROM offres_vues WHERE created_at < now() - INTERVAL '60 days'$$);


-- ============================================================
-- Row Level Security (RLS)
-- ============================================================

ALTER TABLE user_data   ENABLE ROW LEVEL SECURITY;
ALTER TABLE offres_vues ENABLE ROW LEVEL SECURITY;

-- user_data : chaque utilisateur ne voit et ne modifie que ses propres données
CREATE POLICY "user_data_self" ON user_data
    FOR ALL USING (auth.uid()::text = user_id);

-- offres_vues : lecture/écriture via service_role uniquement (orchestrateur backend)
-- Le frontend n'a pas besoin d'accéder à cette table directement
CREATE POLICY "offres_vues_service" ON offres_vues
    FOR ALL USING (auth.role() = 'service_role');
>>>>>>> 65403d4e252353fd6afb24e82c4c3935b2017d79
