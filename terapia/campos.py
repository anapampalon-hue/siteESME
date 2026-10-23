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
import hashlib
import hmac
import os
import secrets
import unicodedata
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


# ---------------------------------------------------------------------------------------------
# PSEUDÔNIMO DO PACIENTE
# Em vez do nome, o histórico, o CSV e o relatório (por padrão) usam um CÓDIGO como "P-7K3Q9X".
#   * o código sai de um HMAC-SHA256 do nome (sem acento, minúsculo) + a conta da fisio, com uma chave SECRETA
#     que não está no banco: sem a chave não dá para descobrir o nome a partir do código, nem testar nomes "no chute";
#   * o mesmo nome (na mesma conta) sempre dá o mesmo código, então dá para ver a evolução de uma pessoa sem o nome;
#   * a ligação código -> nome é o próprio campo criptografado Sessao.paciente_nome, guardado à parte.
# A chave do pseudônimo é OUTRA, diferente da chave de criptografia: ESME_CHAVE_PSEUDO ou
# <projeto>/dados_privados/chave_pseudonimo.key (criada na 1ª vez). Guarde uma cópia: se ela mudar, os códigos mudam.
# ---------------------------------------------------------------------------------------------
_ALFABETO = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'      # sem letras que se confundem (I, L, O, 0, 1)


@lru_cache(maxsize=1)
def _chave_pseudonimo():
    chave = os.environ.get('ESME_CHAVE_PSEUDO')
    if not chave:
        caminho = Path(getattr(settings, 'ESME_ARQUIVO_CHAVE_PSEUDO', Path(settings.BASE_DIR) / 'dados_privados' / 'chave_pseudonimo.key'))
        if not caminho.exists():
            caminho.parent.mkdir(parents=True, exist_ok=True)
            caminho.write_text(secrets.token_hex(32))
            try:
                caminho.chmod(0o600)
            except OSError:
                pass
        chave = caminho.read_text().strip()
    return chave.encode('utf-8')


def normalizar_nome(nome):
    """'  Maria  da SILVA ' e 'maria da silva' contam como o mesmo paciente."""
    sem_acento = ''.join(c for c in unicodedata.normalize('NFD', nome or '') if unicodedata.category(c) != 'Mn')
    return ' '.join(sem_acento.lower().split())


def codigo_paciente(fisio_id, nome):
    """Código pseudônimo estável do paciente dentro da conta da fisio. Vazio se não houver nome."""
    base = normalizar_nome(nome)
    if not base:
        return ''
    h = hmac.new(_chave_pseudonimo(), f'{fisio_id}|{base}'.encode('utf-8'), hashlib.sha256).digest()
    return 'P-' + ''.join(_ALFABETO[b % len(_ALFABETO)] for b in h[:6])