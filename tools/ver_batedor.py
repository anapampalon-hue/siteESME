"""
ver_batedor.py — confere se o batedor está mandando dados de verdade (e se os números fazem sentido).

Rode na pasta do projeto (onde está o manage.py), COM O SERVIDOR (runserver) DESLIGADO, porque o site e este
script usam a mesma porta (4210) e só um dos dois pode ficar com ela:
    python tools\\ver_batedor.py
    python tools\\ver_batedor.py --csv batedor.csv      (grava as amostras para abrir no Octave/MATLAB/Excel)
    python tools\\ver_batedor.py --segundos 30          (para sozinho depois de 30 s)

A placa manda os pacotes para o último IP que aprendeu (o aviso que o site manda pela rede). Por isso:
deixe o site rodando até o "Batedor" ficar verde, feche o site (Ctrl+C no terminal dele) e só então rode este script.
Se a placa for religada com o site fechado, ela volta ao IP gravado pelo cabo USB na página Configurações.

Uma linha por segundo:
  pct/s      pacotes que chegaram por segundo (esperado: 25)
  amostras/s amostras novas por segundo (esperado: 100)
  buracos    amostras que nunca chegaram (os pacotes se repetem, então 1 pacote perdido não deixa buraco)
  perdidos   pacotes perdidos, pelo contador do pacote
  intervalo  tempo entre amostras pelo relógio da placa (esperado: 10 ms; máx. grande = a placa travou um instante)
  |a|        tamanho da aceleração em g. Com o batedor PARADO deve dar perto de 1,00 g.
  ax ay az   última amostra em g
Quando o batedor leva uma pancada, o |a| máx. sobe; o site considera "impacto" a partir de 14 g (o sensor satura em 16 g).

Ele não muda nada no site nem nas placas; só escuta e mostra.
"""
import argparse
import csv
import math
import os
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from terapia.protocolo import decodificar_batedor   # o MESMO decodificador do site

LSB_POR_G = 2048.0          # MPU-6050 em ±16 g
IMPACTO_G = 14.0            # igual ao fluidez.py
SEM_SINAL_S = 2.0           # igual ao estado.py


def _norma_g(ax, ay, az):
    return math.sqrt(ax * ax + ay * ay + az * az) / LSB_POR_G


def main():
    ap = argparse.ArgumentParser(description='Confere os dados do batedor.')
    ap.add_argument('--porta', type=int, default=4210, help='porta UDP (padrão 4210)')
    ap.add_argument('--csv', help='arquivo CSV para gravar as amostras (seq,t_us,ax,ay,az,gx,gy,gz,chegada_s)')
    ap.add_argument('--segundos', type=float, default=0, help='parar sozinho depois deste tempo (0 = até Ctrl+C)')
    a = ap.parse_args()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(('0.0.0.0', a.porta))
    except OSError:
        print(f'A porta {a.porta} já está em uso. O site (runserver) deve estar ligado: feche-o (Ctrl+C no terminal dele) e rode de novo.')
        return 1
    s.settimeout(0.25)

    arq = escritor = None
    if a.csv:
        arq = open(a.csv, 'w', newline='', encoding='utf-8')
        escritor = csv.writer(arq)
        escritor.writerow(['seq', 't_us', 'ax', 'ay', 'az', 'gx', 'gy', 'gz', 'chegada_s'])

    print(f'Escutando o batedor na porta {a.porta}. Mexa o batedor; Ctrl+C para parar.')
    t0 = time.monotonic()
    prox_linha = t0 + 1.0
    ult_pkt = None
    ult_seq = None
    ult_t_us = None
    ultimo_pacote = None
    # contadores do segundo atual
    seg = dict(pct=0, novas=0, buracos=0, perdidos=0, dts=[], normas=[])
    ultima = None
    # totais
    tot = dict(pct=0, novas=0, buracos=0, perdidos=0, reinicios=0, seg_impacto=0, seg_total=0, max_g=0.0)

    def zerar():
        seg.update(pct=0, novas=0, buracos=0, perdidos=0, dts=[], normas=[])

    try:
        while True:
            agora = time.monotonic()
            if a.segundos and agora - t0 >= a.segundos:
                break
            try:
                dados, _origem = s.recvfrom(2048)
                chegada = time.monotonic()
            except socket.timeout:
                dados = None
            if dados is not None:
                p = decodificar_batedor(dados)
                if p is not None:
                    ultimo_pacote = chegada
                    seg['pct'] += 1
                    tot['pct'] += 1
                    if ult_pkt is not None:
                        perdidos = ((p.pkt - ult_pkt) & 0xFFFF) - 1
                        if 0 < perdidos < 1000:
                            seg['perdidos'] += perdidos
                            tot['perdidos'] += perdidos
                    ult_pkt = p.pkt
                    for (seq, t_us, ax, ay, az, gx, gy, gz) in p.amostras:
                        if ult_seq is not None:
                            d = (seq - ult_seq) & 0xFFFFFFFF
                            if d == 0 or (d >= 0x80000000 and ((ult_seq - seq) & 0xFFFFFFFF) < 64):
                                continue                    # amostra repetida (vem em dois pacotes) ou atrasada
                            if d >= 0x80000000:             # salto grande para trás: a placa reiniciou
                                tot['reinicios'] += 1
                                print('  >> a placa reiniciou (o contador de amostras voltou)')
                            elif d > 1:
                                seg['buracos'] += d - 1
                                tot['buracos'] += d - 1
                        if ult_t_us is not None and ult_seq is not None and ((seq - ult_seq) & 0xFFFFFFFF) == 1:
                            seg['dts'].append(((t_us - ult_t_us) & 0xFFFFFFFF) / 1000.0)
                        ult_seq, ult_t_us = seq, t_us
                        seg['novas'] += 1
                        tot['novas'] += 1
                        n = _norma_g(ax, ay, az)
                        seg['normas'].append(n)
                        ultima = (ax, ay, az)
                        if escritor:
                            escritor.writerow([seq, t_us, ax, ay, az, gx, gy, gz, f'{chegada - t0:.4f}'])
            agora = time.monotonic()
            if agora >= prox_linha:
                prox_linha += 1.0
                decorrido = int(agora - t0)
                if seg['pct'] == 0:
                    quando = ultimo_pacote
                    sem = None if quando is None else round(agora - quando)
                    txt = 'nenhum pacote ainda' if sem is None else f'sem pacotes há {sem} s'
                    print(f'[{decorrido:3d} s] {txt}' + ('  (= "Sem sinal" no site)' if sem is None or sem >= SEM_SINAL_S else ''))
                else:
                    ns = seg['normas']
                    dts = seg['dts']
                    tot['seg_total'] += 1
                    tot['max_g'] = max(tot['max_g'], max(ns))
                    if max(ns) >= IMPACTO_G:
                        tot['seg_impacto'] += 1
                    inter = f'{sorted(dts)[len(dts) // 2]:.1f} ms (máx {max(dts):.1f})' if dts else '-'
                    ult = f'ax {ultima[0] / LSB_POR_G:+.2f}  ay {ultima[1] / LSB_POR_G:+.2f}  az {ultima[2] / LSB_POR_G:+.2f} g' if ultima else ''
                    print(f'[{decorrido:3d} s] {seg["pct"]:2d} pct/s · {seg["novas"]:3d} amostras/s · buracos {seg["buracos"]} · '
                          f'perdidos {seg["perdidos"]} · intervalo {inter} · '
                          f'|a| {sum(ns) / len(ns):.2f} g (mín {min(ns):.2f} · máx {max(ns):.2f}) · {ult}')
                zerar()
    except KeyboardInterrupt:
        pass
    finally:
        if arq:
            arq.close()
        s.close()

    dur = max(time.monotonic() - t0, 1e-9)
    print('\nResumo')
    print(f'  {tot["pct"]} pacotes · {tot["novas"]} amostras em {dur:.0f} s'
          f' ({tot["pct"] / dur:.1f} pct/s, {tot["novas"] / dur:.1f} amostras/s)')
    print(f'  buracos: {tot["buracos"]} · pacotes perdidos: {tot["perdidos"]} · reinícios da placa: {tot["reinicios"]}')
    if tot['seg_total']:
        print(f'  maior |a|: {tot["max_g"]:.2f} g · segundos com impacto (≥ {IMPACTO_G:.0f} g): {tot["seg_impacto"]}')
    if a.csv:
        print(f'  amostras gravadas em {a.csv}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
