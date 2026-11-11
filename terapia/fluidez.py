"""
fluidez.py (rev. 2026-11-09) — FLUIDEZ de uma tentativa a partir das amostras do batedor (escopo do Sandro, seção 9.2).

Roda em SEGUNDO PLANO (estado.py chama isto numa thread própria): enquanto uma tentativa mostra "Calculando fluidez…",
as próximas já podem ser jogadas.

POR QUE MUDOU. Com as gravações reais de 09/11 (12 tentativas) a conta antiga integrava a aceleração da tentativa INTEIRA
(do "nova tentativa" até 3 s depois de o disco parar). O batedor fica parado por muitos segundos antes da tacada; qualquer
erro minúsculo (0,01 g na referência, 0,5 °/s no giroscópio) vira uma RAMPA na velocidade (17 s de batedor parado deram
"18,8 m/s"; 168 s deram "1296 m/s"), e como a escala do gráfico é a mesma para todas as tentativas, essa rampa achatava
todas as outras curvas. Agora:

  1. acha os trechos em que o batedor está PARADO (desvio da aceleração e do giroscópio no nível do ruído do sensor);
  2. o que fica entre dois trechos parados é um MOVIMENTO. A velocidade é integrada só dentro dele, começando em zero
     (o batedor estava parado) e, quando o batedor volta a ficar parado, forçada a voltar a zero (a sobra é deriva e é
     retirada linearmente). Erro de segundos vira erro de décimos de segundo;
  3. a referência de repouso é o trecho parado logo antes do movimento (se não houver, o último repouso da sessão;
     se também não houver -> "indisponível, sem repouso de referência");
  4. a tacada é o movimento com a maior velocidade; a curva do Detalhe é só ele, e a fluidez é o número de picos dele.

Depois do impacto o sensor pode saturar (±16 g): se aparecer uma amostra ≥ IMPACTO_G o movimento termina ali.

*** Os limites abaixo são PROVISÓRIOS. O escopo diz que só dá para ajustá-los com gravações reais do batedor. ***
Só Python puro (sem NumPy), como o analise_fluidez.py.
"""
import math

G = 9.80665                 # m/s² por 1 g
LSB_POR_G = 2048.0          # MPU-6050 na faixa de ±16 g
LSB_POR_DPS = 32.8          # giroscópio na faixa de ±1000 °/s (batedor_esme.ino)
IMPACTO_G = 14.0            # a partir daqui o sensor está saturando = impacto no disco
MIN_AMOSTRAS = 20
VEL_MIN = 0.15              # m/s — abaixo disto não houve movimento de verdade
VEL_MAX = 8.0               # m/s — acima disto (≈ 29 km/h) o resultado não é confiável (deriva): trata como "sem dados"
PROMINENCIA = 0.10          # um pico precisa sobressair ≥ 10% do pico maior em relação ao vale vizinho
PONTOS_CURVA = 60

# "parado" = em janelas de PARADO_JANELA_S o desvio padrão de cada eixo fica perto do ruído de quando o batedor está
# quieto. Esse ruído muda muito: batedor apoiado na mesa ≈ 0,004–0,01 g e 0,1–0,3 °/s; batedor segurado na mão
# (tremor) ≈ 0,02–0,04 g e 2–6 °/s. Por isso o limite é ADAPTATIVO: 3× o ruído "de repouso" da própria tentativa
# (percentil PARADO_PERCENTIL das janelas), mas nunca abaixo do piso nem acima do teto.
PARADO_JANELA_S = 0.20
PARADO_PERCENTIL = 0.20
PARADO_FATOR = 3.0
PARADO_ACC_G = 0.02         # piso do limite do desvio padrão da aceleração, por eixo (g)
PARADO_ACC_MAX_G = 0.07     # teto
PARADO_GIRO_DPS = 1.5       # piso do limite do desvio padrão do giroscópio, por eixo (°/s)
PARADO_GIRO_MAX_DPS = 9.0   # teto
PARADO_MIN_S = 0.30         # um trecho parado precisa durar pelo menos isto para valer como referência
REPOUSO_S = 0.25            # o repouso de referência é a média dos últimos 0,25 s do trecho parado
MOV_MIN_AMOSTRAS = 5        # menos que isto não é movimento (é um solavanco)


def _media(xs):
    return sum(xs) / len(xs)


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
        cand.append(len(v) - 1)              # ainda subindo no fim do movimento: o fim conta como pico
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


def _alinhar_com_giroscopio(ac, giro, t, vies):
    """Gira cada aceleração de volta para a posição em que o batedor estava no fim do repouso.
    Sem isso, se o batedor se inclina durante a tacada, parte da gravidade (9,8 m/s²) passa a aparecer no eixo do
    movimento. Só é usada DENTRO de um movimento (décimos de segundo), onde o erro do giroscópio é desprezível.
    ac: aceleração por amostra (m/s², [x, y, z]); giro: giroscópio bruto por amostra; vies: giroscópio parado (bruto)."""
    R = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    saida = [list(ac[0])]
    w_ant = [math.radians((giro[0][k] - vies[k]) / LSB_POR_DPS) for k in range(3)]
    for i in range(1, len(ac)):
        w = [math.radians((giro[i][k] - vies[k]) / LSB_POR_DPS) for k in range(3)]
        dt = t[i] - t[i - 1]
        wm = [(w[k] + w_ant[k]) / 2 for k in range(3)]               # velocidade angular média entre as duas amostras
        w_ant = w
        ang = math.sqrt(sum(x * x for x in wm)) * dt
        if ang > 1e-9:
            e = [x * dt / ang for x in wm]
            K = [[0.0, -e[2], e[1]], [e[2], 0.0, -e[0]], [-e[1], e[0], 0.0]]
            K2 = [[sum(K[r][m] * K[m][q] for m in range(3)) for q in range(3)] for r in range(3)]
            s_, c_ = math.sin(ang), math.cos(ang)
            dR = [[(1.0 if r == q else 0.0) + s_ * K[r][q] + (1 - c_) * K2[r][q] for q in range(3)] for r in range(3)]   # Rodrigues
            R = [[sum(R[r][m] * dR[m][q] for m in range(3)) for q in range(3)] for r in range(3)]
        saida.append([sum(R[r][m] * ac[i][m] for m in range(3)) for r in range(3)])
    return saida


def _trechos_parados(t, canais):
    """Lista de (i0, i1) com os trechos em que o batedor está parado há pelo menos PARADO_MIN_S.
    canais = 6 listas: ax, ay, az (g) e gx, gy, gz (°/s). Parado = em toda janela de PARADO_JANELA_S o desvio padrão de
    cada eixo está abaixo do limite adaptativo (somas acumuladas: O(n), serve para tentativas de minutos)."""
    n = len(t)
    s1, s2 = [], []
    for c in canais:
        m = _media(c)
        a, b = [0.0], [0.0]
        for x in c:
            x -= m
            a.append(a[-1] + x)
            b.append(b[-1] + x * x)
        s1.append(a)
        s2.append(b)
    janelas = []                                            # (i, j, desvio máx. da aceleração, desvio máx. do giro)
    j = 0
    for i in range(n):
        if j < i:
            j = i
        while j + 1 < n and t[j + 1] - t[i] <= PARADO_JANELA_S:
            j += 1
        k = j - i + 1
        if k < 8:
            continue
        dp = []
        for c in range(6):
            soma = s1[c][j + 1] - s1[c][i]
            dp.append(math.sqrt(max(0.0, (s2[c][j + 1] - s2[c][i]) / k - (soma / k) ** 2)))
        janelas.append((i, j, max(dp[:3]), max(dp[3:])))
    if not janelas:
        return []
    def limite(valores, piso, teto):
        v = sorted(valores)
        return min(teto, max(piso, PARADO_FATOR * v[int(PARADO_PERCENTIL * (len(v) - 1))]))
    lim_a = limite([w[2] for w in janelas], PARADO_ACC_G, PARADO_ACC_MAX_G)
    lim_g = limite([w[3] for w in janelas], PARADO_GIRO_DPS, PARADO_GIRO_MAX_DPS)
    parado = [0] * (n + 1)                                  # diferença acumulada: marca as amostras de toda janela parada
    for i, j, da, dg in janelas:
        if da <= lim_a and dg <= lim_g:
            parado[i] += 1
            parado[j + 1] -= 1
    trechos, acc, ini = [], 0, None
    for i in range(n):
        acc += parado[i]
        if acc > 0 and ini is None:
            ini = i
        if acc <= 0 and ini is not None:
            if t[i - 1] - t[ini] >= PARADO_MIN_S:
                trechos.append((ini, i - 1))
            ini = None
    if ini is not None and t[n - 1] - t[ini] >= PARADO_MIN_S:
        trechos.append((ini, n - 1))
    return trechos


def _repouso_do_trecho(t, ac, giro, i0, i1):
    """Aceleração (m/s²) e giroscópio (bruto) médios dos últimos REPOUSO_S do trecho parado [i0, i1]."""
    k = i1
    while k > i0 and t[i1] - t[k - 1] <= REPOUSO_S:
        k -= 1
    rep = [_media([ac[i][c] for i in range(k, i1 + 1)]) for c in range(3)]
    if giro:
        rep += [_media([giro[i][c] for i in range(k, i1 + 1)]) for c in range(3)]
    return rep


def _velocidade(t, ac, giro, s, e, rep, parou_depois):
    """Velocidade (m/s) do movimento [s, e], começando em zero. Se o batedor volta a ficar parado (parou_depois), a
    velocidade final tem de ser zero: a sobra é deriva e é retirada linearmente. Devolve (tempos, velocidades)."""
    tt = t[s:e + 1]
    ac_mov = ac[s:e + 1]
    if giro and len(rep) >= 6:
        ac_mov = _alinhar_com_giroscopio(ac_mov, giro[s:e + 1], tt, rep[3:6])
    lin = [[v[k] - rep[k] for k in range(3)] for v in ac_mov]
    u = _direcao_principal(lin)
    p = [sum(v[k] * u[k] for k in range(3)) for v in lin]
    p = [_media(p[max(0, i - 2):i + 3]) for i in range(len(p))]             # suaviza (média móvel de 5)
    v = [0.0]
    for i in range(len(p) - 1):
        v.append(v[-1] + (tt[i + 1] - tt[i]) * (p[i] + p[i + 1]) / 2)
    if parou_depois and len(v) > 1:
        dur = tt[-1] - tt[0]
        if dur > 0:
            v = [x - v[-1] * (t_ - tt[0]) / dur for x, t_ in zip(v, tt)]
    if abs(min(v)) > abs(max(v)):                                           # o sinal do eixo é arbitrário
        v = [-x for x in v]
    return tt, v


def calcular(amostras, ref_repouso=None):
    """amostras: [(t_segundos, ax, ay, az[, gx, gy, gz]), ...] em unidades brutas do sensor, da tentativa inteira.
    Devolve {'nivel': 'alta'|'media'|'baixa'|'indisponivel', 'motivo': ..., 'picos': n, 'curva': {...}, 'repouso': [...]}.
    'repouso' é o último repouso medido (para a próxima tentativa usar se não houver trecho parado)."""
    sem_dados = {'nivel': 'indisponivel', 'motivo': 'sem_dados_batedor'}
    amostras = sorted(amostras)
    if len(amostras) < MIN_AMOSTRAS:
        return sem_dados
    t = [a[0] for a in amostras]
    ac = [[a[k] / LSB_POR_G * G for k in (1, 2, 3)] for a in amostras]      # m/s² por eixo
    giro = [list(a[4:7]) for a in amostras] if len(amostras[0]) >= 7 else None
    canais = [[a[k] / LSB_POR_G for a in amostras] for k in (1, 2, 3)]
    canais += [[a[k] / LSB_POR_DPS for a in amostras] for k in (4, 5, 6)] if giro else [[0.0] * len(amostras)] * 3

    parados = _trechos_parados(t, canais)
    repouso_novo = _repouso_do_trecho(t, ac, giro, *parados[-1]) if parados else None   # o último, p/ a próxima tentativa
    base = {'repouso': repouso_novo}
    if not parados and ref_repouso is None:
        return {'nivel': 'indisponivel', 'motivo': 'sem_repouso'}

    # movimentos = o que fica entre dois trechos parados (ou entre o começo/fim da tentativa e um trecho parado)
    n = len(t)
    limites = []
    if parados:
        limites.append((None, parados[0]))
        limites += [(parados[k], parados[k + 1]) for k in range(len(parados) - 1)]
        limites.append((parados[-1], None))
    else:
        limites.append((None, None))
    melhor = None                                                           # (vmax, tt, v, parou_depois)
    for antes, depois in limites:
        s = antes[1] + 1 if antes else 0
        e = depois[0] - 1 if depois else n - 1
        for i in range(s, e + 1):                                           # impacto: o sensor satura, o movimento acaba ali
            if math.sqrt(sum(x * x for x in ac[i])) / G >= IMPACTO_G:
                e, depois = i - 1, None
                break
        if e - s + 1 < MOV_MIN_AMOSTRAS:
            continue
        if antes:
            rep = _repouso_do_trecho(t, ac, giro, *antes)
        elif ref_repouso is not None:
            rep = ref_repouso
        else:
            continue
        tt, v = _velocidade(t, ac, giro, s, e, rep, depois is not None)
        vmax = max(v)
        if vmax > VEL_MAX:
            continue
        if melhor is None or vmax > melhor[0]:
            melhor = (vmax, tt, v, depois is not None)

    if melhor is None or melhor[0] < VEL_MIN:
        return {**sem_dados, **base}
    vmax, tt, v, _ = melhor

    n_picos = len(_picos(v, vmax))
    nivel = 'alta' if n_picos == 1 else 'media' if n_picos == 2 else 'baixa'
    passo = max(1, len(v) // PONTOS_CURVA)
    pontos = [[round(tt[i] - tt[0], 3), round(max(0.0, v[i]), 3)] for i in range(0, len(v), passo)]
    return {**base, 'nivel': nivel, 'picos': n_picos, 'curva': {'pontos': pontos, 'v_max': round(vmax, 3)}}