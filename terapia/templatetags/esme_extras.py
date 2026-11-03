"""Tags de template do ESME. Uso:  {% load esme_extras %}  ...  {% navbar "inicio" %}"""
from django import template

from .. import rede

register = template.Library()


@register.inclusion_tag('terapia/_navbar.html')
def navbar(ativa=''):
    """Barra de cima: Início · Configurações · Sobre nós. `ativa` = 'inicio' | 'configuracoes' | 'sobre' (ou vazio).
    A aba Configurações ganha um sinal quando falta configurar as placas."""
    ok, _motivo = rede.configuracao_ok()
    return {'ativa': ativa, 'falta_configurar': not ok}