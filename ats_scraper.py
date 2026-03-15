# Alias pour l'orchestrateur : from ats_scraper import scraper_tous_ats
import os
import importlib.util
_dir = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_ats", os.path.join(_dir, "2_ats_scraper.py"))
_ats = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ats)
scraper_tous_ats = _ats.scraper_tous_ats
