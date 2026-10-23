"""
receptor.py — escuta os pacotes UDP das placas e entrega ao estado.py.

Mesa (ESP32) -> porta 4212 | Batedor (ESP8266) -> porta 4210 (escopo do Sandro, seção 3).
Um thread por porta. Este arquivo só RECEBE. O aviso do IP do notebook para as placas é feito por anuncio.py.
Se a porta estiver ocupada (outro receptor aberto), o programa segue funcionando e o Diagnóstico mostra "ocupada".
"""
import logging
import socket
import threading
import time

from .estado import programa
from .protocolo import decodificar_batedor, decodificar_mesa

log = logging.getLogger('esme.receptor')
_iniciado = False


def _ouvir(porta, decodificar, entregar):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('0.0.0.0', porta))      # as placas estão em OUTRO aparelho: precisa ouvir a rede, não só 127.0.0.1
    except OSError as erro:
        programa.portas[porta] = 'ocupada'
        print(f'[ESME] ATENÇÃO: não consegui abrir a porta UDP {porta} ({erro}). Outro programa pode estar usando.', flush=True)
        return
    programa.portas[porta] = 'livre'
    sock.settimeout(1.0)
    print(f'[ESME] Ouvindo UDP na porta {porta}', flush=True)       # aparece no terminal do runserver
    recebidos = 0
    while True:
        try:
            dados, _origem = sock.recvfrom(2048)
        except socket.timeout:
            continue
        except ConnectionResetError:
            continue                    # Windows avisa assim quando um remetente some; não é erro
        except OSError as erro:
            log.error('Erro na porta %s: %s', porta, erro)
            time.sleep(0.5)
            continue
        pacote = decodificar(dados)
        if pacote is None:             # pacote malformado é descartado
            continue
        recebidos += 1
        if recebidos == 1:
            print(f'[ESME] Primeiro pacote recebido na porta {porta} (de {_origem[0]})', flush=True)
        entregar(pacote)


def iniciar(porta_mesa=4212, porta_batedor=4210):
    global _iniciado
    if _iniciado:
        return
    _iniciado = True
    for porta, dec, ent in ((porta_mesa, decodificar_mesa, programa.ao_receber_mesa),
                            (porta_batedor, decodificar_batedor, programa.ao_receber_batedor)):
        threading.Thread(target=_ouvir, args=(porta, dec, ent), name=f'udp-{porta}', daemon=True).start()