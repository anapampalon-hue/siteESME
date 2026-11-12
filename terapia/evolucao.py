"""Linha de evolução: média das curvas de velocidade do paciente, com o tempo de cada tentativa normalizado (0 a 100 %).

Cada tentativa vale um voto (uma sessão com 6 tentativas pesa mais que uma com 2). Só entram tentativas concluídas,
não anuladas, com curva, de sessões não anônimas do mesmo código de paciente. Nada é guardado: calcula-se ao abrir."""
from .models import Tentativa

PONTOS = 100


def normalizar(curva, so_forma=False, k=PONTOS):
    """Curva {'pontos': [[t, v], ...], 'v_max': x} -> k valores de velocidade, em k instantes de 0 a 100 % do tempo."""
    pts = curva.get('pontos') or []
    if len(pts) < 2:
        return None
    t0, t1 = pts[0][0], pts[-1][0]
    if t1 <= t0:
        return None
    escala = (curva.get('v_max') or max(v for _, v in pts) or 1) if so_forma else 1
    saida, j = [], 0
    for i in range(k):
        alvo = t0 + (t1 - t0) * i / (k - 1)
        while j < len(pts) - 2 and pts[j + 1][0] < alvo:
            j += 1
        (ta, va), (tb, vb) = pts[j], pts[j + 1]
        f = 0 if tb == ta else min(1, max(0, (alvo - ta) / (tb - ta)))
        saida.append((va + (vb - va) * f) / escala)
    return saida


def media(listas):
    """Média ponto a ponto (cada lista = 1 tentativa). Devolve {'y', 'dp', 'n'} ou None se não há nenhuma."""
    listas = [x for x in listas if x]
    if not listas:
        return None
    n = len(listas)
    y = [sum(c[i] for c in listas) / n for i in range(PONTOS)]
    dp = [(sum((c[i] - y[i]) ** 2 for c in listas) / n) ** 0.5 for i in range(PONTOS)]
    return {'y': [round(v, 4) for v in y], 'dp': [round(v, 4) for v in dp], 'n': n}


def _tentativas_do_paciente(sessao, ate_esta=True):
    if sessao.anonima or not sessao.codigo_paciente:
        return Tentativa.objects.none()
    qs = Tentativa.objects.filter(
        sessao__in=type(sessao).objects.ativas().filter(anonima=False, codigo_paciente=sessao.codigo_paciente),
        finalizada_em__isnull=False, anulada=False, curva__isnull=False,
    )
    return qs.filter(sessao__pk__lt=sessao.pk) if ate_esta else qs


def _grupo(qs, so_forma):
    curvas = list(qs.values_list('curva', flat=True))
    m = media([normalizar(c, so_forma) for c in curvas if c])
    return m


def evolucao_da_sessao(sessao, so_forma=False):
    """As 3 linhas: antes da sessão (sessões anteriores), esta sessão e a evolução atualizada (as duas juntas)."""
    antes_qs = _tentativas_do_paciente(sessao)
    esta_qs = Tentativa.objects.filter(sessao=sessao, finalizada_em__isnull=False, anulada=False, curva__isnull=False)
    antes = list(antes_qs.values_list('curva', flat=True))
    esta = list(esta_qs.values_list('curva', flat=True))
    na = [normalizar(c, so_forma) for c in antes if c]
    ne = [normalizar(c, so_forma) for c in esta if c]
    return {
        'antes': media(na), 'esta': media(ne), 'atualizada': media(na + ne),
        'sessoes_antes': antes_qs.values('sessao_id').distinct().count(),
    }