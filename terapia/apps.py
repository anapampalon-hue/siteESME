import os
import sys

from django.apps import AppConfig
from django.conf import settings


def _deve_iniciar_receptor():
    if not getattr(settings, 'ESME_RECEPTOR', True):
        return False
    argv = sys.argv
    if len(argv) > 1 and argv[1] == 'runserver':
        # o runserver cria 2 processos; só o filho (RUN_MAIN) deve abrir as portas
        return os.environ.get('RUN_MAIN') == 'true' or '--noreload' in argv
    if len(argv) > 1 and os.path.basename(argv[0]).startswith('manage'):
        return False      # migrate, makemigrations, shell, test... não abrem porta
    return True


class TerapiaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'terapia'

    def ready(self):
        if _deve_iniciar_receptor():
            from . import receptor
            receptor.iniciar(
                getattr(settings, 'ESME_PORTA_MESA', 4212),
                getattr(settings, 'ESME_PORTA_BATEDOR', 4210),
            )