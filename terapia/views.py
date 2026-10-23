import json

from django.contrib.auth.decorators import login_required
from django.db.utils import OperationalError, ProgrammingError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .estado import programa
from .models import eh_gestor


def _nome_da_conta(request):
    fisio = getattr(request.user, 'fisioterapeuta', None)
    # superadmin pode não ter perfil de fisio: cai no nome de usuário
    return fisio.nome if fisio else request.user.get_username()


@login_required
def home(request):
    return render(request, 'terapia/home.html', {'nome': _nome_da_conta(request), 'eh_gestor': eh_gestor(request.user)})


@login_required
@ensure_csrf_cookie      # a tela manda comandos por fetch e precisa do cookie CSRF
def nova_sessao(request):
    return render(request, 'terapia/nova_sessao.html')


@login_required
@ensure_csrf_cookie
def espera_mesa(request):
    return render(request, 'terapia/espera_mesa.html')


@login_required
@ensure_csrf_cookie
def sessao(request):
    return render(request, 'terapia/sessao.html', {'nome': _nome_da_conta(request)})


# ---------------------------------------------------------------------------
# API que a tela usa (contrato do Sandro, seção 12): estado completo + comandos
# ---------------------------------------------------------------------------
def _nao_logado():
    return JsonResponse({'ok': False, 'erro': 'sem_permissao'}, status=401)


@require_GET
def api_estado(request):
    if not request.user.is_authenticated:
        return _nao_logado()
    try:
        corpo = programa.snapshot(request.user)
    except (OperationalError, ProgrammingError) as erro:
        # quase sempre: models.py mudou e falta rodar "python manage.py migrate"
        print('[ESME] ERRO no banco de dados:', erro)
        print('[ESME] >>> Pare o site (Ctrl+C) e rode:  python manage.py makemigrations   e depois   python manage.py migrate')
        return JsonResponse({'ok': False, 'erro': 'banco_desatualizado'}, status=500)
    resposta = JsonResponse(corpo)
    resposta['Cache-Control'] = 'no-store'
    return resposta


@require_POST
def api_comando(request):
    """POST {"nome": "...", "args": {...}} -> {"ok": true, ...} ou {"ok": false, "erro": "codigo"}"""
    if not request.user.is_authenticated:
        return _nao_logado()
    try:
        corpo = json.loads(request.body or b'{}')
        nome, args = corpo.get('nome'), corpo.get('args') or {}
        if not isinstance(args, dict):
            raise ValueError
    except ValueError:
        return JsonResponse({'ok': False, 'erro': 'pedido_invalido'}, status=400)

    u = request.user
    if nome == 'preparar_sessao':
        r = programa.preparar_sessao(u, args.get('paciente'), args.get('data'))
    elif nome == 'cancelar_espera':
        r = programa.cancelar_espera(u)
    elif nome == 'encerrar_sessao':
        r = programa.encerrar_sessao(u)
    elif nome in ('anular', 'restaurar', 'obter_curva'):
        try:
            numero = int(args.get('numero'))
        except (TypeError, ValueError):
            return JsonResponse({'ok': False, 'erro': 'pedido_invalido'}, status=400)
        if nome == 'obter_curva':
            r = programa.obter_curva(u, numero)
        else:
            r = programa.anular(u, numero) if nome == 'anular' else programa.restaurar(u, numero)
    elif nome == 'fechar_leitura':
        r = programa.fechar_leitura(u)
    elif nome == 'sugestoes_nome':
        r = programa.sugestoes_nome(u, args.get('prefixo'))
    else:
        r = {'ok': False, 'erro': 'comando_desconhecido'}     # gerar_pdf, abrir_pasta... entram na etapa do PDF
    return JsonResponse(r)