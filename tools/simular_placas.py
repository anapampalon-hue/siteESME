"""
simular_placas.py — SÓ PARA DESENVOLVIMENTO: manda pacotes UDP no formato das placas para o site,
para testar o caminho inteiro sem a mesa e sem o batedor (a tela não tem simulador nenhum).

Uso (com o site rodando; deixe esta janela aberta):
    python tools\\simular_placas.py                 # mesa + batedor vivos (bolinhas verdes)
    python tools\\simular_placas.py --aperto        # ...e simula o aperto de 3 s do "nova sessão" após 6 s
    python tools\\simular_placas.py --tentativas    # ...e depois joga tentativas sozinho (a tabela vai enchendo)
    python tools\\simular_placas.py --sem-batedor   # só a mesa
    python tools\\simular_placas.py --mesa-antiga   # mesa no formato de teste antigo (8 bytes: sem contador)
    python tools\\simular_placas.py --host 192.168.0.10
Pare com Ctrl+C.

Formato dos pacotes: o de terapia/protocolo.py (mesa: provisório; batedor: Anexo A.4 do escopo).
"""
import argparse
import random
import socket
import struct
import time

ap = argparse.ArgumentParser()
ap.add_argument('--host', default='127.0.0.1')
ap.add_argument('--porta-mesa', type=int, default=4212)
ap.add_argument('--porta-batedor', type=int, default=4210)
ap.add_argument('--sem-batedor', action='store_true')
ap.add_argument('--mesa-antiga', action='store_true')
ap.add_argument('--aperto', action='store_true', help='simula o aperto de 3 s depois de 6 s')
ap.add_argument('--tentativas', action='store_true', help='depois do aperto, joga tentativas sozinho')
a = ap.parse_args()
if a.tentativas:
    a.aperto = True

CAB = struct.Struct('<BHHHBBIB')      # estado, boot_id, contador_sessao, contador_tentativas, bobina_max, motivo_fim, t_us, n_eventos
EVT = struct.Struct('<IBBI')          # ev_id, tipo, valor, t_us
INICIO, BOBINA, GOL, FIM = 1, 2, 3, 4
MOT_GOL, MOT_PAROU, MOT_NOVA_TENT = 1, 2, 3

# roteiro das tentativas: (bobinas cruzadas, como termina, nº de "tacadas" do batedor)
#   1 tacada = movimento fluido (fluidez alta) · 2 = média · 3 ou 4 = entrecortado (baixa)
ROTEIRO = [(4, 'parou', 1), (8, 'gol', 1), (2, 'parou', 3)]
TACADA = {1: (0.50, 0.30), 2: (0.25, 0.15), 3: (0.20, 0.10), 4: (0.20, 0.075)}   # (duração s, distância m)
movimentos = []                       # (início, duração, distância) de cada tacada do batedor
impactos = []                         # instante em que o batedor bate no disco (o sensor satura)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
t0 = time.monotonic()
pkt_mesa = pkt_bat = seq = 0
contador_sessao = contador_tent = bobina_max = ev_id = 0
estado, motivo_fim = 1, 0
eventos = []                          # (instante, ev_id, tipo, valor, t_us)
agenda = []                           # (instante, funcao) ações futuras do roteiro
aperto_feito = False
prox_mesa = prox_bat = 0.0
ultimo_aviso = -1


def evento(agora, tipo, valor=0):
    global ev_id
    ev_id += 1
    eventos.append((agora, ev_id, tipo, valor, int(agora * 1e6) & 0xFFFFFFFF))


def jerk_minimo(x, t0, T, D):
    """Aceleração (m/s²) de um movimento de jerk mínimo que percorre D metros em T segundos."""
    if x < t0 or x > t0 + T:
        return 0.0
    tau = (x - t0) / T
    return 30 * D / T ** 2 * (2 * tau - 6 * tau ** 2 + 4 * tau ** 3)


def planejar(inicio):
    """Monta no relógio o roteiro: cada tentativa começa, o batedor dá as tacadas e bate no disco,
    o disco cruza as bobinas (0,8 s cada) e a tentativa termina."""
    t = inicio
    for n, fim, tacadas in ROTEIRO:
        agenda.append((t, 'inicio', 0))
        T, D = TACADA[tacadas]
        for k in range(tacadas):                       # as tacadas terminam no impacto, 1,6 s depois do início
            movimentos.append((t + 1.6 - 0.03 - (tacadas - k) * (T + 0.03), T, D))
        impactos.append(t + 1.6 - 0.03)
        t += 1.6
        for b in range(1, n + 1):
            agenda.append((t, 'bobina', b)); t += 0.8
        if fim == 'gol':
            agenda.append((t, 'gol', 0)); t += 0.1
            agenda.append((t, 'fim', MOT_GOL)); t += 4.0
        elif fim == 'parou':
            t += 3.0                                   # a mesa espera 3 s sem nova bobina
            agenda.append((t, 'fim', MOT_PAROU)); t += 4.0
        else:                                          # aperta nova tentativa antes do fim
            t += 1.0
    return t


print('Enviando para', a.host, '- Ctrl+C para parar')
try:
    while True:
        agora = time.monotonic() - t0
        t_us = int(agora * 1e6) & 0xFFFFFFFF
        if a.aperto and not aperto_feito and agora > 6:
            contador_sessao += 1; aperto_feito = True
            print('aperto de 3 s simulado (contador_sessao ->', contador_sessao, ')')
            if a.tentativas:
                planejar(agora + 3)
                print('vou jogar', len(ROTEIRO), 'tentativas, uma depois da outra...')
        while agenda and agenda[0][0] <= agora:        # ações do roteiro que chegaram a hora
            _, acao, v = agenda.pop(0)
            if acao == 'inicio':
                contador_tent += 1; bobina_max = 0; estado = 2; motivo_fim = 0
                evento(agora, INICIO); print('  tentativa', contador_tent, 'iniciada')
            elif acao == 'bobina':
                bobina_max = v; evento(agora, BOBINA, v)
            elif acao == 'gol':
                evento(agora, GOL); bobina_max = 8
            elif acao == 'fim':
                motivo_fim = v; estado = 3; evento(agora, FIM, v)
                print('  fim:', {1: 'gol', 2: 'parou'}[v])
        if agora >= prox_mesa:                         # a cada 100 ms: estado inteiro + eventos dos últimos 2 s
            pkt_mesa += 1; prox_mesa += 0.1
            eventos[:] = [e for e in eventos if agora - e[0] <= 2.0][-16:]
            if a.mesa_antiga:
                dados = struct.pack('<II', pkt_mesa, t_us)
            else:
                dados = CAB.pack(estado, 7, contador_sessao, contador_tent, bobina_max, motivo_fim, t_us, len(eventos))
                dados += b''.join(EVT.pack(e[1], e[2], e[3], e[4]) for e in eventos)
            sock.sendto(dados, (a.host, a.porta_mesa))
        if not a.sem_batedor and agora >= prox_bat:    # batedor: 25 pacotes por segundo
            prox_bat += 0.04; pkt_bat += 1
            amostras = b''
            for k in range(4):
                seq += 1
                x = agora - (3 - k) * 0.01                 # 100 amostras por segundo
                ax = sum(jerk_minimo(x, *m) for m in movimentos) / 9.80665 * 2048
                ax = int(ax + 30 + random.gauss(0, 25))
                if any(i <= x < i + 0.02 for i in impactos):
                    ax = 32767                             # impacto: o sensor satura (±16 g)
                amostras += struct.pack('<IIhhhhhh', seq, int(x * 1e6) & 0xFFFFFFFF, ax,
                                        int(random.gauss(0, 25)), int(2048 + random.gauss(0, 25)), 0, 0, 0)
            sock.sendto(struct.pack('<HBB', pkt_bat, 4, 4) + amostras, (a.host, a.porta_batedor))
        if int(agora) != ultimo_aviso:
            ultimo_aviso = int(agora)
            if ultimo_aviso % 5 == 0:
                print(f'  ... {pkt_mesa} pacotes da mesa e {pkt_bat} do batedor enviados')
        time.sleep(0.005)
except KeyboardInterrupt:
    pass