# Module alias pour l'orchestrateur : from france_travail import ...
import os
import importlib.util
_dir = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_ft", os.path.join(_dir, "1_france_travail.py"))
_ft = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ft)

rechercher_offres = _ft.rechercher_offres
get_offres_recentes = _ft.get_offres_recentes
