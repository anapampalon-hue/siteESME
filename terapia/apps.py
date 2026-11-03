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
        # ao sair da conta, nenhuma sessão anônima fica para trás
        from django.contrib.auth.signals import user_logged_out

        def _ao_sair(sender, **kwargs):
            from .estado import programa
            programa.descartar_anonimas()
        user_logged_out.connect(_ao_sair, dispatch_uid='esme_descartar_anonimas')

        if _deve_iniciar_receptor():
            from . import receptor
            receptor.iniciar(
                getattr(settings, 'ESME_PORTA_MESA', 4212),
                getattr(settings, 'ESME_PORTA_BATEDOR', 4210),
            )
            if getattr(settings, 'ESME_ANUNCIO', True):
                from . import anuncio          # o notebook avisa seu IP na rede (as placas o acham sozinhas)
                anuncio.iniciar(
                    getattr(settings, 'ESME_PORTA_MESA', 4212),
                    getattr(settings, 'ESME_PORTA_BATEDOR', 4210),
                )