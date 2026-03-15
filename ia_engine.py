# Alias pour l'orchestrateur : from ia_engine import ...
import os
import importlib.util
_dir = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_ia", os.path.join(_dir, "3_ia_engine.py"))
_ia = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ia)
analyser_cv = _ia.analyser_cv
scorer_compatibilite = _ia.scorer_compatibilite
adapter_cv = _ia.adapter_cv
generer_lettre_motivation = _ia.generer_lettre_motivation
