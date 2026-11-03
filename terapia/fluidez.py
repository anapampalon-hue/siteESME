"""
fluidez.py — calcula a FLUIDEZ de uma tentativa a partir das amostras do batedor (escopo do Sandro, seção 9.2).

Roda em SEGUNDO PLANO (estado.py chama isto numa thread própria), então a terapeuta não espera: enquanto uma
tentativa mostra "Calculando fluidez…", as próximas já podem ser jogadas.

Passos (os mesmos do escopo):
  1. pega as amostras do acelerômetro do começo da tentativa até o IMPACTO (depois dele o sensor satura);
  2. referência de repouso: o trecho parado logo no começo; se não houver, o último repouso da sessão;
     se também não houver -> "indisponível, sem repouso de referência";
  3. aceleração (sem o repouso) projetada no eixo do movimento -> velocidade por integral numérica (trapézio);
  4. classifica pelo número de picos de velocidade: 1 = alta · 2 = média · 3 ou mais = baixa.

*** Os limites abaixo são PROVISÓRIOS. O escopo diz que só dá para ajustá-los com gravações reais do batedor. ***
Só Python puro (sem NumPy), como o analise_fluidez.py.
"""
import math

G = 9.80665                 # m/s² por 1 g
LSB_POR_G = 2048.0          # MPU-6050 na faixa de ±16 g
IMPACTO_G = 14.0            # a partir daqui o sensor está saturando = impacto no disco
REPOUSO_S = 0.30            # tamanho do trecho parado usado como referência
REPOUSO_DESVIO_G = 0.06     # "parado" = variação abaixo disto em cada eixo
MIN_AMOSTRAS = 20
VEL_MIN = 0.15              # m/s — abaixo disto não houve movimento de verdade
PROMINENCIA = 0.10          # um pico precisa sobressair ≥ 10% do pico maior em relação ao vale vizinho
PONTOS_CURVA = 60


def _media(xs):
    return sum(xs) / len(xs)


def _desvio(xs):
    m = _media(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def _direcao_principal(vetores):
    """Eixo em que a aceleração mais varia (iteração de potência no tensor 3x3)."""
    c = [[sum(v[i] * v[j] for v in vetores) for j in range(3)] for i in range(3)]
    u = [1.0, 0.3, 0.1]
    for _ in range(30):
        w = [sum(c[i][j] * u[j] for j in range(3)) for i in range(3)]
        n = math.sqrt(sum(x * x for x in w))
        if n < 1e-12:
            break
        u = [x / n for x in w]
    return u


def _picos(v, vmax):
    """Índices dos picos de velocidade que sobressaem de verdade (descarta ruído)."""
    cand = [i for i in range(1, len(v) - 1) if v[i - 1] < v[i] >= v[i + 1] and v[i] > 0.05 * vmax]
    if len(v) >= 2 and v[-1] > v[-2] and v[-1] > 0.05 * vmax:
        cand.append(len(v) - 1)              # ainda subindo no impacto: o fim conta como pico
    mudou = True
    while mudou and len(cand) > 1:
        mudou = False
        for k in range(len(cand) - 1):
            a, b = cand[k], cand[k + 1]
            vale = min(v[a:b + 1])
            if min(v[a], v[b]) - vale < PROMINENCIA * vmax:
                cand.pop(k if v[a] < v[b] else k + 1)
                mudou = True
                break
    return cand


def calcular(amostras, ref_repouso=None):
    """amostras: [(t_segundos, ax, ay, az), ...] em unidades brutas do sensor, da tentativa inteira.
    Devolve {'nivel': 'alta'|'media'|'baixa'|'indisponivel', 'motivo': ..., 'picos': n, 'curva': {...}, 'repouso': [...]}.
    'repouso' é o viés medido (para a próxima tentativa usar se não houver trecho parado)."""
    sem_dados = {'nivel': 'indisponivel', 'motivo': 'sem_dados_batedor'}
    amostras = sorted(amostras)
    if len(amostras) < MIN_AMOSTRAS:
        return sem_dados

    # 1) corta no impacto
    fim = len(amostras)
    for i, (_, ax, ay, az) in enumerate(amostras):
        if math.sqrt(ax * ax + ay * ay + az * az) / LSB_POR_G >= IMPACTO_G:
            fim = i
            break
    amostras = amostras[:fim]
    if len(amostras) < MIN_AMOSTRAS:
        return sem_dados
    t = [a[0] for a in amostras]
    ac = [[a[k] / LSB_POR_G * G for k in (1, 2, 3)] for a in amostras]      # m/s² por eixo

    # 2) repouso de referência: o começo da tentativa, se o batedor estiver parado
    n_rep = sum(1 for x in t if x - t[0] <= REPOUSO_S)
    repouso = None
    if n_rep >= 8:
        eixos = [[v[k] for v in ac[:n_rep]] for k in range(3)]
        if all(_desvio(e) / G < REPOUSO_DESVIO_G for e in eixos):
            repouso = [_media(e) for e in eixos]
    achou_repouso = repouso is not None
    if repouso is None:
        repouso = ref_repouso
    if repouso is None:
        return {'nivel': 'indisponivel', 'motivo': 'sem_repouso'}
    ini = n_rep if achou_repouso else 0
    if len(amostras) - ini < 10:
        return sem_dados

    # 3) aceleração sem o repouso, projetada no eixo do movimento, e integral por trapézio
    lin = [[v[k] - repouso[k] for k in range(3)] for v in ac[ini:]]
    u = _direcao_principal(lin)
    p = [sum(v[k] * u[k] for k in range(3)) for v in lin]
    p = [_media(p[max(0, i - 2):i + 3]) for i in range(len(p))]             # suaviza (média móvel de 5)
    tt = t[ini:]
    v = [0.0]
    for i in range(len(p) - 1):
        v.append(v[-1] + (tt[i + 1] - tt[i]) * (p[i] + p[i + 1]) / 2)
    if abs(min(v)) > abs(max(v)):                                           # o sinal do eixo é arbitrário
        v = [-x for x in v]
    vmax = max(v)
    base = {'repouso': repouso if achou_repouso else None}
    if vmax < VEL_MIN:
        return {**sem_dados, **base}

    # 4) classifica pelo número de picos
    n = len(_picos(v, vmax))
    nivel = 'alta' if n == 1 else 'media' if n == 2 else 'baixa'

    # curva para o Detalhe: do começo do movimento até o impacto, no máximo PONTOS_CURVA pontos
    i0 = next((i for i, x in enumerate(v) if x > 0.05 * vmax), 0)
    i0 = max(0, i0 - 1)
    passo = max(1, (len(v) - i0) // PONTOS_CURVA)
    pontos = [[round(tt[i] - tt[i0], 3), round(max(0.0, v[i]), 3)] for i in range(i0, len(v), passo)]
    return {**base, 'nivel': nivel, 'picos': n, 'curva': {'pontos': pontos, 'v_max': round(vmax, 3)}}