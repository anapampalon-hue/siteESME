"""
placas.py — conversa com as placas (mesa ESP32 e batedor ESP8266) pelo cabo USB, para gravar o Wi-Fi nelas.

Quem conversa é o próprio programa (biblioteca pyserial): a terapeuta não abre prompt de comando nem escolhe porta.
Protocolo (texto, uma linha por mensagem, 115200 bauds) — a descrição completa para o firmware está em protocolo-serial.md:

    notebook -> placa :  ESME?
    placa -> notebook :  ESME;MESA;1.0           (ou ESME;BATEDOR;1.0)
    notebook -> placa :  CFG;1;<nome da rede em base64>;<senha em base64>;<ip do notebook>
    placa -> notebook :  OK;WIFI;<ip da placa>   (entrou no Wi-Fi e guardou a rede na memória)
                         ERRO;<CODIGO>           (REDE_NAO_ENCONTRADA, SENHA_INCORRETA, TEMPO_ESGOTADO, COMANDO_INVALIDO, FLASH)

A SENHA NUNCA é guardada nem escrita em log: ela só passa por variáveis locais daqui até a porta USB.
Abrir a porta serial costuma reiniciar a placa (ESP). Por isso se espera o boot e se repete o "ESME?" até ela responder.
"""
import base64
import re
import threading
import time

from django.views.decorators.debug import sensitive_variables

try:
    import serial
    from serial.tools import list_ports
except ImportError:                      # o site abre mesmo sem pyserial; só a configuração das placas avisa
    serial = None
    list_ports = None

BAUD = 115200
VERSAO_PROTOCOLO = 1
ESPERA_IDENTIFICAR_S = 7.0               # ESP reinicia ao abrir a porta: dá tempo de ligar e responder
ESPERA_WIFI_S = 30.0                     # entrar no Wi-Fi demora
_RESPOSTA_ID = re.compile(r'^ESME;(MESA|BATEDOR);([0-9A-Za-z._-]{1,12})$')

_trava = threading.RLock()               # uma conversa serial por vez
_conhecidas = {}                         # porta -> {'tipo','versao','erro'} (para não reiniciar a placa a cada olhada)


def disponivel():
    return serial is not None


# ------------------------------------------------------------------ portas
def _listar_portas():
    """Portas USB do notebook. Portas sem fabricante (Bluetooth, COM1 de placa-mãe) ficam de fora."""
    saida = []
    for p in list_ports.comports():
        if p.vid is not None:
            saida.append({'porta': p.device, 'descricao': p.description or ''})
    return sorted(saida, key=lambda x: x['porta'])


def _abrir(porta):
    return serial.Serial(porta, BAUD, timeout=0.25, write_timeout=3)


def _erro_de_porta(erro):
    texto = str(erro).lower()
    if 'permission' in texto or 'denied' in texto or 'busy' in texto or 'acesso' in texto:
        return 'porta_ocupada'               # outro programa (Arduino IDE, monitor serial) está usando a porta
    return 'erro_porta'


def _linhas(conexao, ate):
    """Gera as linhas recebidas até o instante `ate` (as que não são texto são ignoradas: lixo do boot)."""
    resto = b''
    while time.monotonic() < ate:
        resto += conexao.read(256)
        while b'\n' in resto:
            bruta, resto = resto.split(b'\n', 1)
            yield bruta.decode('utf-8', 'ignore').strip()
    return


def _perguntar_quem_e(conexao, ate):
    """Manda ESME? de tempos em tempos até a placa responder. Devolve {'tipo','versao'} ou None."""
    proximo_envio = 0.0
    resto = b''
    while time.monotonic() < ate:
        agora = time.monotonic()
        if agora >= proximo_envio:
            conexao.write(b'ESME?\n')
            proximo_envio = agora + 0.6
        resto += conexao.read(256)
        while b'\n' in resto:
            bruta, resto = resto.split(b'\n', 1)
            m = _RESPOSTA_ID.match(bruta.decode('utf-8', 'ignore').strip())
            if m:
                return {'tipo': m.group(1), 'versao': m.group(2)}
    return None


def identificar(porta):
    """Abre a porta e pergunta à placa quem ela é. {'ok': True, 'tipo','versao'} ou {'ok': False, 'erro': codigo}."""
    with _trava:
        try:
            conexao = _abrir(porta)
        except (OSError, serial.SerialException) as erro:
            return {'ok': False, 'erro': _erro_de_porta(erro)}
        try:
            quem = _perguntar_quem_e(conexao, time.monotonic() + ESPERA_IDENTIFICAR_S)
        except (OSError, serial.SerialException):
            return {'ok': False, 'erro': 'erro_porta'}
        finally:
            conexao.close()
        return dict(quem, ok=True) if quem else {'ok': False, 'erro': 'sem_resposta'}


def placas_ligadas(forcar=False):
    """
    Lista as placas USB ligadas, identificando cada uma só UMA vez (abrir a porta reinicia a placa).
    [{'porta','tipo','versao','erro'}]  — 'tipo' é None se não deu para identificar (e 'erro' diz por quê).
    `forcar=True` (botão "Procurar de novo") esquece o que já sabia.
    """
    with _trava:
        portas = {p['porta'] for p in _listar_portas()}
        for p in list(_conhecidas):
            if p not in portas or forcar:
                _conhecidas.pop(p, None)                      # placa desligada (ou pedido para olhar de novo)
        for p in sorted(portas):
            if p not in _conhecidas:
                r = identificar(p)
                _conhecidas[p] = {'tipo': r.get('tipo'), 'versao': r.get('versao'), 'erro': r.get('erro')}
        return [dict(porta=p, **_conhecidas[p]) for p in sorted(portas)]


# ------------------------------------------------------------------ gravar a rede
def _b64(texto):
    return base64.b64encode(texto.encode('utf-8')).decode('ascii')


@sensitive_variables('senha', 'comando')
def gravar(tipo, ssid, senha, ip):
    """
    Grava nome da rede, senha e IP do notebook na placa `tipo` (MESA ou BATEDOR), que deve ser a ÚNICA ligada.
    {'ok': True, 'ip_placa': '192.168.x.y'} ou {'ok': False, 'erro': codigo}.
    """
    with _trava:
        ligadas = placas_ligadas()
        if not ligadas:
            return {'ok': False, 'erro': 'nenhuma_placa'}
        if len(ligadas) > 1:
            return {'ok': False, 'erro': 'varias_placas'}
        alvo = ligadas[0]
        if alvo['tipo'] is None:
            return {'ok': False, 'erro': alvo['erro'] or 'sem_resposta'}
        if alvo['tipo'] != tipo:
            return {'ok': False, 'erro': 'placa_errada'}

        try:
            conexao = _abrir(alvo['porta'])
        except (OSError, serial.SerialException) as erro:
            _conhecidas.pop(alvo['porta'], None)
            return {'ok': False, 'erro': _erro_de_porta(erro)}
        try:
            quem = _perguntar_quem_e(conexao, time.monotonic() + ESPERA_IDENTIFICAR_S)   # a placa reiniciou ao abrir
            if quem is None:
                _conhecidas.pop(alvo['porta'], None)
                return {'ok': False, 'erro': 'sem_resposta'}
            if quem['tipo'] != tipo:
                _conhecidas.pop(alvo['porta'], None)
                return {'ok': False, 'erro': 'placa_errada'}

            comando = f'CFG;{VERSAO_PROTOCOLO};{_b64(ssid)};{_b64(senha)};{ip}\n'.encode('ascii')
            conexao.reset_input_buffer()
            conexao.write(comando)
            conexao.flush()
            comando = b''
            for linha in _linhas(conexao, time.monotonic() + ESPERA_WIFI_S):
                if linha.startswith('OK;WIFI'):
                    partes = linha.split(';')
                    return {'ok': True, 'ip_placa': partes[2] if len(partes) > 2 else ''}
                if linha.startswith('ERRO;'):
                    return {'ok': False, 'erro': linha.split(';', 1)[1].strip().lower()[:40] or 'erro_placa'}
            return {'ok': False, 'erro': 'tempo_esgotado'}
        except (OSError, serial.SerialException):
            return {'ok': False, 'erro': 'erro_porta'}
        finally:
            conexao.close()