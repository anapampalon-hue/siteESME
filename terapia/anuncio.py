"""
anuncio.py — o notebook avisa na rede "o programa está neste IP" (escopo do Sandro, seção 14.1).

Uma vez por segundo, em cada rede em que o notebook está, vai um pacote UDP de broadcast para a porta 4200:

    ESME-IP;1;<ip_do_notebook>;<porta_da_mesa>;<porta_do_batedor>

As placas escutam esse aviso e mandam os pacotes para quem avisou; o IP gravado pelo cabo USB (Configurações)
fica só como reserva. Assim, se o hotspot der outro IP ao notebook, as placas continuam achando o programa.
Não leva nenhum dado de paciente. Desligar: ESME_ANUNCIO = False no settings.py.
"""
import socket
import threading
import time

from . import rede

PORTA_ANUNCIO = 4200
_iniciado = False


def _mensagem(ip, porta_mesa, porta_batedor):
    return f'ESME-IP;1;{ip};{porta_mesa};{porta_batedor}'.encode('ascii')


def _enviar_uma_vez(porta_mesa, porta_batedor):
    for ip, broadcast in rede.enderecos_de_broadcast():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.bind((ip, 0))                       # sai pela placa de rede certa, com o IP certo no aviso
            s.sendto(_mensagem(ip, porta_mesa, porta_batedor), (broadcast, PORTA_ANUNCIO))
        except OSError:
            pass                                   # rede caiu no meio: tenta de novo no próximo segundo
        finally:
            s.close()


def _laco(porta_mesa, porta_batedor):
    print(f'[ESME] Anunciando o IP do notebook na rede (UDP {PORTA_ANUNCIO}), 1 vez por segundo', flush=True)
    while True:
        try:
            _enviar_uma_vez(porta_mesa, porta_batedor)
        except Exception as erro:                  # o anúncio nunca pode derrubar o programa
            print(f'[ESME] anúncio de IP: {erro}', flush=True)
        time.sleep(1.0)


def iniciar(porta_mesa=4212, porta_batedor=4210):
    global _iniciado
    if _iniciado:
        return
    _iniciado = True
    threading.Thread(target=_laco, args=(porta_mesa, porta_batedor), daemon=True, name='esme-anuncio').start()