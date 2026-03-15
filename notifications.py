# Alias pour l'orchestrateur : from notifications import envoyer_notification_offre
import os
import importlib.util
_dir = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("_notif", os.path.join(_dir, "4_notifications.py"))
_notif = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_notif)
envoyer_notification_offre = _notif.envoyer_notification_offre
