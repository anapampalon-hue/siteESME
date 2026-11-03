"""
equipe.py — o que a página Equipe (só da supervisora) faz com os perfis das terapeutas.

  * criar_perfil     : nome + senha  ->  login (User) + perfil (Fisioterapeuta, papel "fisio")
  * definir_senha    : a supervisora digita uma nova senha
  * alternar_ativo   : desativar (bolinha cinza, não consegue entrar, histórico mantido) / reativar
  * excluir          : só o perfil (se não tiver sessões) ou o perfil E todas as sessões dela

A senha entra em duas formas: o hash do Django (é com ele que a terapeuta entra) e uma cópia CRIPTOGRAFADA
(Fisioterapeuta.senha_visivel, mesma chave dos nomes dos pacientes) para a supervisora poder rever no perfil.
Supervisoras (papel super_fisio) não são mexidas por aqui: continuam sendo geridas pelo /admin.
"""
import re
import unicodedata

from django.contrib.auth import get_user_model
from django.db import transaction

from .models import Fisioterapeuta, Sessao

SENHA_MIN, SENHA_MAX = 6, 64
NOME_MAX = 150

ERROS = {
    'nome_vazio': 'Digite o nome da terapeuta.',
    'nome_longo': f'O nome pode ter no máximo {NOME_MAX} letras.',
    'nome_repetido': 'Já existe um perfil com esse nome. Acrescente um sobrenome ou uma inicial.',
    'senha_curta': f'A senha precisa ter pelo menos {SENHA_MIN} caracteres.',
    'senha_longa': f'A senha pode ter no máximo {SENHA_MAX} caracteres.',
    'senha_espacos': 'A senha não pode começar nem terminar com espaço.',
}


def _validar_senha(senha):
    if not isinstance(senha, str) or len(senha) < SENHA_MIN:
        return 'senha_curta'
    if len(senha) > SENHA_MAX:
        return 'senha_longa'
    if senha != senha.strip() or '\n' in senha or '\r' in senha:
        return 'senha_espacos'
    return None


def _usuario_livre(nome):
    """'Maria da Silva' -> 'maria.da.silva' (e '.2', '.3'... se já existir). É só o nome interno do login."""
    sem_acento = ''.join(c for c in unicodedata.normalize('NFD', nome) if unicodedata.category(c) != 'Mn')
    base = re.sub(r'[^a-z0-9]+', '.', sem_acento.lower()).strip('.')[:24] or 'terapeuta'
    User = get_user_model()
    candidato, n = base, 1
    while User.objects.filter(username=candidato).exists():
        n += 1
        candidato = f'{base}.{n}'
    return candidato


def criar_perfil(nome, senha):
    """(fisio, None) ou (None, codigo_do_erro)."""
    nome = ' '.join((nome or '').split())
    if not nome:
        return None, 'nome_vazio'
    if len(nome) > NOME_MAX:
        return None, 'nome_longo'
    if Fisioterapeuta.objects.filter(nome__iexact=nome).exists():
        return None, 'nome_repetido'
    erro = _validar_senha(senha)
    if erro:
        return None, erro
    with transaction.atomic():
        user = get_user_model().objects.create_user(username=_usuario_livre(nome), password=senha)
        fisio = Fisioterapeuta.objects.create(user=user, nome=nome, papel=Fisioterapeuta.Papel.FISIO,
                                              ativo=True, senha_visivel=senha)
    return fisio, None


def definir_senha(fisio, senha):
    erro = _validar_senha(senha)
    if erro:
        return erro
    with transaction.atomic():
        fisio.user.set_password(senha)
        fisio.user.save(update_fields=['password'])
        fisio.senha_visivel = senha
        fisio.save(update_fields=['senha_visivel'])
    return None


def alternar_ativo(fisio, ativo):
    fisio.ativo = bool(ativo)
    fisio.save()                      # o save() do modelo também liga/desliga o login (user.is_active)


def total_sessoes(fisio):
    return Sessao.objects.filter(fisioterapeuta=fisio).count()


def excluir(fisio, com_sessoes):
    """Apaga o perfil e o login. Com sessões salvas, só se `com_sessoes` (aí elas são apagadas de vez, com tentativas e curvas).
    Devolve 'tem_sessoes' se faltou a permissão para apagar as sessões; senão None."""
    with transaction.atomic():
        sessoes = Sessao.objects.filter(fisioterapeuta=fisio)
        if sessoes.exists():
            if not com_sessoes:
                return 'tem_sessoes'
            sessoes.delete()
        fisio.user.delete()           # leva o perfil junto (CASCADE)
    return None