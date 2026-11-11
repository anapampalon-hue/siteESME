import json
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles import finders
from django.db.models import Count
from django.db.utils import OperationalError, ProgrammingError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.templatetags.static import static
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_GET, require_POST

from . import equipe as equipe_logica, placas, rede
from .estado import programa
from .exportar import dados_relatorio, gerar_csv
from .models import Fisioterapeuta, Sessao, eh_gestor


def _nome_da_conta(request):
    fisio = getattr(request.user, 'fisioterapeuta', None)
    # superadmin pode não ter perfil de fisio: cai no nome de usuário
    return fisio.nome if fisio else request.user.get_username()


@login_required
def home(request):
    configurado, _motivo = rede.configuracao_ok()      # o botão "Nova sessão" só fica ativo com as placas configuradas
    return render(request, 'terapia/home.html', {'nome': _nome_da_conta(request), 'eh_gestor': eh_gestor(request.user),
                                                 'configurado': configurado})


@login_required
@ensure_csrf_cookie
def configuracoes(request):
    return render(request, 'terapia/configuracoes.html')


@login_required
def sobre(request):
    return render(request, 'terapia/sobre.html')


@login_required
@ensure_csrf_cookie      # a tela manda comandos por fetch e precisa do cookie CSRF
def nova_sessao(request):
    if not rede.configuracao_ok()[0]:
        return redirect('configuracoes')               # sem configurar as placas não se começa sessão nova
    # o link "Ler o TCLE" só aparece quando o PDF existir: coloque-o em terapia/static/terapia/docs/tcle.pdf
    tcle_pdf = static('terapia/docs/tcle.pdf') if finders.find('terapia/docs/tcle.pdf') else None
    return render(request, 'terapia/nova_sessao.html', {'tcle_pdf': tcle_pdf})


@login_required
@ensure_csrf_cookie
def espera_mesa(request):
    return render(request, 'terapia/espera_mesa.html')


@login_required
@ensure_csrf_cookie
def sessao(request):
    return render(request, 'terapia/sessao.html', {'nome': _nome_da_conta(request)})


@login_required
@ensure_csrf_cookie
def historico(request):
    return render(request, 'terapia/historico.html')


# ---------------------------------------------------------------------------
# EQUIPE (só a supervisora): lista de terapeutas, novo perfil e o perfil de cada uma
# ---------------------------------------------------------------------------
def so_supervisora(view):
    """Quem não é supervisora volta para o Início (a terapeuta nem vê o botão Equipe)."""
    @wraps(view)
    def interna(request, *args, **kwargs):
        if not eh_gestor(request.user):
            return redirect('home')
        return view(request, *args, **kwargs)
    return login_required(interna)


_AVISOS_EQUIPE = {
    'criado': ('ok', 'Perfil criado.'),
    'senha': ('ok', 'Senha atualizada.'),
    'ativado': ('ok', 'Perfil reativado.'),
    'desativado': ('ok', 'Perfil desativado. A terapeuta não consegue mais entrar, e o histórico dela continua salvo.'),
    'excluido': ('ok', 'Perfil excluído.'),
    'em_uso': ('erro', 'Esta terapeuta está com uma sessão aberta agora. Espere a sessão acabar e tente de novo.'),
    'tem_sessoes': ('erro', 'Esta terapeuta tem sessões salvas. Desative o perfil, ou escolha apagar o perfil junto com as sessões.'),
    'sem_acao': ('erro', 'Este perfil não pode ser alterado por aqui.'),
}


def _aviso_equipe(request):
    chave = request.GET.get('aviso')
    if chave in equipe_logica.ERROS:
        return {'tipo': 'erro', 'texto': equipe_logica.ERROS[chave]}
    tipo_texto = _AVISOS_EQUIPE.get(chave)
    return {'tipo': tipo_texto[0], 'texto': tipo_texto[1]} if tipo_texto else None


def _perfil_alvo(request, pk):
    """Perfil de terapeuta mexível: existe, não é supervisora e não é a própria conta."""
    fisio = Fisioterapeuta.objects.select_related('user').filter(pk=pk).first()
    if fisio is None:
        raise Http404('Perfil não encontrado.')
    mexivel = not fisio.eh_super_fisio and fisio.user_id != request.user.pk
    return fisio, mexivel


def _volta(pk, aviso):
    return redirect(f"{reverse('equipe_perfil', args=[pk])}?aviso={aviso}")


@so_supervisora
def equipe(request):
    fisios = list(Fisioterapeuta.objects.select_related('user').annotate(n_sessoes=Count('sessoes')).order_by('-ativo', 'nome'))
    return render(request, 'terapia/equipe.html', {'fisios': fisios, 'aviso': _aviso_equipe(request), 'eu': request.user.pk})


@so_supervisora
@sensitive_post_parameters('senha')
def equipe_novo(request):
    erro, nome = None, ''
    if request.method == 'POST':
        nome = request.POST.get('nome', '')
        fisio, erro = equipe_logica.criar_perfil(nome, request.POST.get('senha', ''))
        if fisio:
            return _volta(fisio.pk, 'criado')
    return render(request, 'terapia/equipe_novo.html', {
        'erro': equipe_logica.ERROS.get(erro), 'erro_campo': erro, 'nome': ' '.join(nome.split()),
        'senha_min': equipe_logica.SENHA_MIN, 'senha_max': equipe_logica.SENHA_MAX,
    })


@so_supervisora
def equipe_perfil(request, pk):
    fisio, mexivel = _perfil_alvo(request, pk)
    if fisio.eh_super_fisio:
        return redirect('equipe')                                      # supervisoras são geridas pelo /admin
    mostrar = request.GET.get('mostrar') == '1' and bool(fisio.senha_visivel)
    resposta = render(request, 'terapia/equipe_perfil.html', {
        'f': fisio, 'mexivel': mexivel, 'n_sessoes': equipe_logica.total_sessoes(fisio), 'aviso': _aviso_equipe(request),
        'mostrar': mostrar, 'senha': fisio.senha_visivel if mostrar else '', 'tem_senha': bool(fisio.senha_visivel),
        'senha_min': equipe_logica.SENHA_MIN, 'senha_max': equipe_logica.SENHA_MAX,
    })
    resposta['Cache-Control'] = 'no-store'                            # a senha não fica guardada no navegador
    return resposta


@require_POST
@so_supervisora
@sensitive_post_parameters('senha')
def equipe_senha(request, pk):
    fisio, mexivel = _perfil_alvo(request, pk)
    if not mexivel:
        return _volta(pk, 'sem_acao')
    erro = equipe_logica.definir_senha(fisio, request.POST.get('senha', ''))
    return _volta(pk, erro or 'senha')


@require_POST
@so_supervisora
def equipe_ativo(request, pk):
    fisio, mexivel = _perfil_alvo(request, pk)
    if not mexivel:
        return _volta(pk, 'sem_acao')
    ativar = request.POST.get('ativo') == '1'
    if not ativar and programa.fisio_em_uso(fisio.pk):
        return _volta(pk, 'em_uso')
    equipe_logica.alternar_ativo(fisio, ativar)
    return _volta(pk, 'ativado' if ativar else 'desativado')


@require_POST
@so_supervisora
def equipe_excluir(request, pk):
    fisio, mexivel = _perfil_alvo(request, pk)
    if not mexivel:
        return _volta(pk, 'sem_acao')
    if programa.fisio_em_uso(fisio.pk):
        return _volta(pk, 'em_uso')
    erro = equipe_logica.excluir(fisio, com_sessoes=request.POST.get('modo') == 'tudo')
    if erro:
        return _volta(pk, erro)
    return redirect(f"{reverse('equipe')}?aviso=excluido")


def _sessao_para_exportar(request, pk):
    """Sessão da própria conta (ou de qualquer uma, para o gestor). A que está em andamento ainda não se exporta."""
    s = Sessao.objects.visiveis_para(request.user).select_related('fisioterapeuta').filter(pk=pk).first()
    if s is None or s.pk == programa.sessao_id:
        raise Http404('Sessão não encontrada.')
    return s


@login_required
def relatorio(request, pk):
    """Relatório da sessão: página própria para imprimir / "Salvar como PDF". Sem o nome, a não ser que se peça (?nome=1)."""
    s = _sessao_para_exportar(request, pk)
    com_nome = request.GET.get('nome') == '1' and not s.anonima        # sessão anônima nunca leva nome
    resposta = render(request, 'terapia/relatorio.html', {
        'r': dados_relatorio(s, com_nome), 'pk': s.pk, 'com_nome': com_nome, 'imprimir': request.GET.get('imprimir') == '1',
    })
    resposta['Cache-Control'] = 'no-store'
    return resposta


@login_required
def exportar_csv(request, pk):
    """CSV pseudonimizado (só o código do paciente; sem nome e sem comentário)."""
    s = _sessao_para_exportar(request, pk)
    resposta = HttpResponse(gerar_csv(s), content_type='text/csv; charset=utf-8')
    arquivo = 'esme_anonimo.csv' if s.anonima else f'esme_{s.garantir_codigo()}_{s.data_sessao.isoformat()}.csv'
    resposta['Content-Disposition'] = f'attachment; filename="{arquivo}"'
    resposta['Cache-Control'] = 'no-store'
    return resposta


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


_CODIGOS_TIPO = ('MESA', 'BATEDOR')


@sensitive_variables('args', 'senha')
def _validar_rede(args):
    """(ssid, senha, ip, erro) a partir do que a tela mandou."""
    ssid, senha, ip = args.get('ssid'), args.get('senha') or '', args.get('ip')
    if not isinstance(ssid, str) or not ssid.strip() or len(ssid.encode('utf-8')) > 32:
        return None, None, None, 'ssid_invalido'
    if not isinstance(senha, str) or (senha != '' and not 8 <= len(senha) <= 63):
        return None, None, None, 'senha_invalida'          # WPA2: 8 a 63 caracteres (ou vazia, rede aberta)
    if not isinstance(ip, str) or not rede._ip_privado(ip):
        return None, None, None, 'ip_invalido'
    return ssid, senha, ip, None


@require_POST
@sensitive_variables('corpo', 'args', 'senha')       # a senha do Wi-Fi não pode aparecer em página de erro
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
        if not rede.configuracao_ok()[0]:
            r = {'ok': False, 'erro': 'placas_nao_configuradas'}
        else:
            # sem o "check" do TCLE (ou sem o campo) a sessão é anônima: o mais seguro é o padrão
            r = programa.preparar_sessao(u, args.get('paciente'), args.get('data'), consentimento=args.get('consentimento') is True)
    elif nome == 'config_estado':
        d = rede.detectar(forcar=True)
        r = {'ok': True, 'ssid_atual': d['ssid'], 'ips': d['ips'], 'ip_sugerido': d['ip_sugerido'],
             'pyserial': placas.disponivel(), 'bloqueada': programa.sessao_ocupando_placas(),
             'configurada': rede.ler_configuracao()}
    elif nome == 'config_placas':
        if not placas.disponivel():
            r = {'ok': False, 'erro': 'pyserial_ausente'}
        elif programa.sessao_ocupando_placas():
            r = {'ok': False, 'erro': 'sessao_aberta'}
        else:
            r = {'ok': True, 'placas': placas.placas_ligadas(forcar=bool(args.get('forcar')))}
    elif nome == 'config_gravar':
        ssid, senha, ip, erro = _validar_rede(args)
        if erro:
            r = {'ok': False, 'erro': erro}
        elif args.get('tipo') not in _CODIGOS_TIPO:
            r = {'ok': False, 'erro': 'pedido_invalido'}
        elif not placas.disponivel():
            r = {'ok': False, 'erro': 'pyserial_ausente'}
        elif programa.sessao_ocupando_placas():
            r = {'ok': False, 'erro': 'sessao_aberta'}
        else:
            r = placas.gravar(args['tipo'], ssid, senha, ip)
    elif nome == 'config_concluir':
        ssid, _senha, ip, erro = _validar_rede(dict(args, senha=''))        # aqui a senha nem é lida
        equip = programa.equipamentos()
        if erro:
            r = {'ok': False, 'erro': erro}
        elif equip['mesa'] != 'ok' or equip['batedor'] != 'ok':
            r = {'ok': False, 'erro': 'placas_sem_sinal'}
        else:
            rede.salvar_configuracao(ssid, ip)
            r = {'ok': True}
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
    elif nome == 'salvar_comentario':
        r = programa.salvar_comentario(u, args.get('texto'))
    elif nome == 'abrir_sessao':
        try:
            r = programa.abrir_sessao(u, int(args.get('id')))
        except (TypeError, ValueError):
            return JsonResponse({'ok': False, 'erro': 'pedido_invalido'}, status=400)
    elif nome == 'concluir_interrompida':
        r = programa.concluir_interrompida(u)
    elif nome == 'listar_historico':
        r = programa.listar_historico(u, str(args.get('busca') or '')[:150], str(args.get('data') or '')[:10], bool(args.get('revelar')))
    elif nome == 'sugestoes_nome':
        r = programa.sugestoes_nome(u, args.get('prefixo'))
    else:
        r = {'ok': False, 'erro': 'comando_desconhecido'}     # gerar_pdf, abrir_pasta... entram na etapa do PDF
    return JsonResponse(r)