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
