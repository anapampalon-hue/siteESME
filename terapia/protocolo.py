"""
protocolo.py — decodifica os pacotes UDP que chegam da mesa (ESP32) e do batedor (ESP8266).

ÚNICO arquivo que conhece o formato byte a byte dos pacotes. Se o firmware mudar, muda só aqui.

BATEDOR (porta 4210) — formato definido no Anexo A.4 do escopo do Sandro (little-endian):
    cabeçalho 4 bytes  '<HBB'        pkt, n (amostras, até 8), passo (=4)
    n amostras 20 bytes '<IIhhhhhh'  seq, t_us, ax, ay, az, gx, gy, gz (valores brutos)

MESA (porta 4212) — o conteúdo está aprovado (Sandro, 19/10): NÃO há batimento separado; a cada 100 ms
todo pacote leva o ESTADO INTEIRO da mesa + os EVENTOS dos últimos 2 s (até 16).
    Estado : estado, contador_sessao, contador_tentativas, bobina_max, motivo_fim
    Eventos: tipo 1 = tentativa iniciada · tipo 2 = bobina (1 a 8) · tipo 3 = gol · tipo 4 = fim (com motivo)
    Motivo do fim: gol | parou | nova_tentativa | nova_sessao
  A DISPOSIÇÃO EM BYTES abaixo é PROVISÓRIA (ainda não tenho o formato-pacote-mesa.md do firmware):
    cabeçalho 14 bytes '<BHHHBBIB'  estado, boot_id, contador_sessao, contador_tentativas,
                                     bobina_max, motivo_fim, t_us, n_eventos
    cada evento 10 bytes '<IBBI'     ev_id, tipo, valor, t_us
  Quando o firmware definir os bytes de verdade, ajuste SÓ MESA_CABECALHO, MESA_EVENTO e as tabelas abaixo.
  Também aceito o pacote de teste antigo de 8 bytes '<II' (número + relógio) como "sinal de vida".
"""
import struct
from dataclasses import dataclass, field
from typing import List, Optional

BATEDOR_CABECALHO = struct.Struct('<HBB')
BATEDOR_AMOSTRA = struct.Struct('<IIhhhhhh')

MESA_VIDA = struct.Struct('<II')                       # teste antigo: pkt, t_us
MESA_CABECALHO = struct.Struct('<BHHHBBIB')            # [PROVISÓRIO]
MESA_EVENTO = struct.Struct('<IBBI')                   # [PROVISÓRIO]
MAX_EVENTOS = 16

ESTADOS_MESA = {0: 'travada', 1: 'aguardando', 2: 'em_tentativa', 3: 'fim'}
MOTIVOS_FIM = {0: None, 1: 'gol', 2: 'parou', 3: 'nova_tentativa', 4: 'nova_sessao'}
EV_INICIO, EV_BOBINA, EV_GOL, EV_FIM = 1, 2, 3, 4


@dataclass
class PacoteBatedor:
    pkt: int
    amostras: list          # [(seq, t_us, ax, ay, az, gx, gy, gz), ...]


@dataclass
class Evento:
    ev_id: int
    tipo: int               # EV_INICIO | EV_BOBINA | EV_GOL | EV_FIM
    valor: int              # bobina (1 a 8) no EV_BOBINA; código do motivo no EV_FIM
    t_us: int


@dataclass
class PacoteMesa:
    tipo: str                               # 'vida' | 'estado'
    estado: Optional[str] = None
    boot_id: Optional[int] = None
    contador_sessao: Optional[int] = None   # sobe a cada aperto de 3 s do botão "nova sessão"
    contador_tentativas: Optional[int] = None
    bobina_max: Optional[int] = None
    motivo_fim: Optional[str] = None
    t_us: Optional[int] = None
    eventos: List[Evento] = field(default_factory=list)


def decodificar_batedor(dados: bytes) -> Optional[PacoteBatedor]:
    """Devolve None se o pacote estiver malformado (ele é simplesmente descartado)."""
    if len(dados) < BATEDOR_CABECALHO.size:
        return None
    pkt, n, passo = BATEDOR_CABECALHO.unpack_from(dados, 0)
    if n > 8 or len(dados) != BATEDOR_CABECALHO.size + n * BATEDOR_AMOSTRA.size:
        return None
    amostras = [
        BATEDOR_AMOSTRA.unpack_from(dados, BATEDOR_CABECALHO.size + i * BATEDOR_AMOSTRA.size)
        for i in range(n)
    ]
    return PacoteBatedor(pkt=pkt, amostras=amostras)


def decodificar_mesa(dados: bytes) -> Optional[PacoteMesa]:
    if len(dados) == MESA_VIDA.size:
        _, t_us = MESA_VIDA.unpack(dados)
        return PacoteMesa(tipo='vida', t_us=t_us)
    if len(dados) < MESA_CABECALHO.size:
        return None
    est, boot, c_sessao, c_tent, bmax, motivo, t_us, n = MESA_CABECALHO.unpack_from(dados, 0)
    if n > MAX_EVENTOS or len(dados) != MESA_CABECALHO.size + n * MESA_EVENTO.size:
        return None
    eventos = [Evento(*MESA_EVENTO.unpack_from(dados, MESA_CABECALHO.size + i * MESA_EVENTO.size)) for i in range(n)]
    return PacoteMesa(
        tipo='estado', estado=ESTADOS_MESA.get(est, 'desconhecido'), boot_id=boot,
        contador_sessao=c_sessao, contador_tentativas=c_tent, bobina_max=bmax,
        motivo_fim=MOTIVOS_FIM.get(motivo), t_us=t_us, eventos=eventos,
    )