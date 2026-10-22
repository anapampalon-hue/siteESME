"""
campos.py — campo de texto criptografado no banco (usado no nome do paciente).

Quem abrir o db.sqlite3 (copiar o arquivo, abrir no DB Browser) vê só texto embaralhado.
Fernet (biblioteca `cryptography`): AES-128 + autenticação. Instalar: pip install cryptography

A CHAVE nunca fica no banco nem no repositório:
  1) variável de ambiente ESME_CHAVE, se existir; senão
  2) arquivo settings.ESME_ARQUIVO_CHAVE (padrão: <projeto>/dados_privados/chave_esme.key), criado na 1ª vez.
Coloque 'dados_privados/' no .gitignore e GUARDE UMA CÓPIA DA CHAVE: sem ela os nomes não voltam.

Dados antigos em texto puro continuam legíveis (o campo devolve o texto como está) e passam a ser
gravados criptografados na próxima vez que a sessão for salva.
"""
import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from django import forms
from django.conf import settings
from django.db import models


@lru_cache(maxsize=1)
def _fernet():
    chave = os.environ.get('ESME_CHAVE')
    if not chave:
        caminho = Path(getattr(settings, 'ESME_ARQUIVO_CHAVE', Path(settings.BASE_DIR) / 'dados_privados' / 'chave_esme.key'))
        if not caminho.exists():
            caminho.parent.mkdir(parents=True, exist_ok=True)
            caminho.write_bytes(Fernet.generate_key())
            try:
                caminho.chmod(0o600)
            except OSError:
                pass          # no Windows o chmod quase não faz efeito; a pasta do usuário já é privada
        chave = caminho.read_text().strip()
    return Fernet(chave.encode() if isinstance(chave, str) else chave)


class CampoCriptografado(models.TextField):
    description = 'Texto criptografado (Fernet)'

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ''):
            return value
        return _fernet().encrypt(value.encode('utf-8')).decode('ascii')

    def from_db_value(self, value, expression, connection):
        if value in (None, ''):
            return value
        try:
            return _fernet().decrypt(value.encode('ascii')).decode('utf-8')
        except InvalidToken:
            return value      # registro antigo, ainda em texto puro

    def formfield(self, **kwargs):
        kwargs.setdefault('widget', forms.TextInput)   # TextField usaria uma caixa grande no admin
        return super().formfield(**kwargs)