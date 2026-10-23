"""
rede.py — a rede do notebook: Wi-Fi em que ele está, IP(s) dele e "qual rede foi configurada nas placas".

  * detectar()           -> {'ssid': 'Hotspot' | None, 'ips': [{'ip','interface','wifi','mascara'}], 'ip_sugerido': '...'}
  * salvar_configuracao  -> guarda SÓ nome da rede + IP + data em dados_privados/rede_configurada.json (NUNCA a senha)
  * configuracao_ok()    -> (True/False, motivo): o "Nova sessão" só abre se a configuração foi feita E a rede/IP do
                            notebook continuam os mesmos (se mudou de hotspot ou de IP, tem que configurar de novo).

Chave opcional no settings.py:  ESME_EXIGIR_CONFIGURACAO = False  -> não exige a configuração (para testar com o simulador).
"""
import ipaddress
import json
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from django.conf import settings

try:                      # opcional: com o psutil dá para listar cada placa de rede com a máscara (necessária ao anúncio)
    import psutil
except ImportError:       # sem ele ainda funciona, só com menos detalhe
    psutil = None

_trava = threading.Lock()
_cache = {'em': 0.0, 'dados': None}
CACHE_S = 2.0
_NOME_WIFI = re.compile(r'wi-?fi|wlan|wireless|sem fio', re.I)
_IGNORAR = re.compile(r'virtual|vmware|vbox|hyper-v|vethernet|loopback|wsl|docker|bluetooth|tap-|tun', re.I)


def _arquivo():
    return Path(getattr(settings, 'ESME_ARQUIVO_REDE', Path(settings.BASE_DIR) / 'dados_privados' / 'rede_configurada.json'))


# ---------------------------------------------------------------- Wi-Fi atual
def _decodificar(b):
    for cod in ('utf-8', 'oem', 'cp1252'):
        try:
            return b.decode(cod)
        except (UnicodeDecodeError, LookupError):
            continue
    return b.decode('utf-8', 'replace')


def _ssid_atual():
    """Nome do Wi-Fi em que o notebook está agora (Windows: netsh). Sem Wi-Fi, ou em outro sistema: None."""
    if not sys.platform.startswith('win'):
        return None
    try:
        saida = subprocess.run(['netsh', 'wlan', 'show', 'interfaces'], capture_output=True, timeout=4,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for linha in _decodificar(saida).splitlines():
        m = re.match(r'^\s*SSID\s*:\s*(.+?)\s*$', linha)      # "BSSID" não casa porque o padrão começa em SSID
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------- IP(s) do notebook
def _ip_privado(texto):
    try:
        ip = ipaddress.ip_address(texto)
    except ValueError:
        return False
    return ip.version == 4 and ip.is_private and not ip.is_loopback and not ip.is_link_local


def _candidatos():
    achados = []
    if psutil is not None:
        try:
            stats = psutil.net_if_stats()
            for nome, enderecos in psutil.net_if_addrs().items():
                if nome in stats and not stats[nome].isup:
                    continue
                for e in enderecos:
                    if e.family == socket.AF_INET and _ip_privado(e.address):
                        achados.append({'ip': e.address, 'interface': nome, 'mascara': e.netmask or '255.255.255.0',
                                        'wifi': bool(_NOME_WIFI.search(nome)), 'virtual': bool(_IGNORAR.search(nome))})
        except (OSError, RuntimeError):
            achados = []
    if not achados:                       # plano B, sem psutil
        vistos = set()
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                vistos.add(info[4][0])
        except OSError:
            pass
        try:                              # o IP da saída padrão (UDP "connect" não envia nada)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('10.255.255.255', 1))
            vistos.add(s.getsockname()[0])
            s.close()
        except OSError:
            pass
        achados = [{'ip': ip, 'interface': '', 'mascara': '255.255.255.0', 'wifi': False, 'virtual': False}
                   for ip in sorted(vistos) if _ip_privado(ip)]
    # Wi-Fi primeiro, placas virtuais (VirtualBox, WSL…) por último
    achados.sort(key=lambda c: (c['virtual'], not c['wifi'], c['ip']))
    return achados


def detectar(forcar=False):
    """Rede atual do notebook (guardada por 2 s para a tela poder perguntar à vontade)."""
    with _trava:
        agora = time.monotonic()
        if not forcar and _cache['dados'] is not None and agora - _cache['em'] < CACHE_S:
            return _cache['dados']
        ips = _candidatos()
        dados = {'ssid': _ssid_atual(), 'ips': ips, 'ip_sugerido': ips[0]['ip'] if ips else None}
        _cache.update(em=agora, dados=dados)
        return dados


def enderecos_de_broadcast():
    """[(ip_do_notebook, endereco_de_broadcast)] de cada rede em que ele está (usado pelo anúncio do IP)."""
    saida = []
    for c in detectar()['ips']:
        try:
            rede = ipaddress.ip_network(f"{c['ip']}/{c['mascara']}", strict=False)
            saida.append((c['ip'], str(rede.broadcast_address)))
        except ValueError:
            continue
    return saida


# ---------------------------------------------------------------- "rede configurada" (sem senha!)
def ler_configuracao():
    try:
        d = json.loads(_arquivo().read_text(encoding='utf-8'))
        return {'ssid': d.get('ssid'), 'ip': d['ip'], 'quando': d.get('quando')} if _ip_privado(d.get('ip', '')) else None
    except (OSError, ValueError, KeyError):
        return None


def salvar_configuracao(ssid, ip):
    """Guarda só o nome da rede e o IP. A senha do Wi-Fi nunca passa por aqui."""
    caminho = _arquivo()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps({'ssid': ssid or None, 'ip': ip, 'quando': datetime.now().isoformat(timespec='seconds')},
                                  ensure_ascii=False), encoding='utf-8')


def configuracao_ok():
    """(True, '') se a Nova sessão pode abrir; senão (False, 'nunca' | 'sem_rede' | 'rede_mudou' | 'ip_mudou')."""
    if not getattr(settings, 'ESME_EXIGIR_CONFIGURACAO', True):
        return True, ''
    cfg = ler_configuracao()
    if cfg is None:
        return False, 'nunca'
    atual = detectar()
    if not atual['ips']:
        return False, 'sem_rede'
    if cfg['ssid'] and atual['ssid'] and cfg['ssid'] != atual['ssid']:
        return False, 'rede_mudou'
    if cfg['ip'] not in {c['ip'] for c in atual['ips']}:
        return False, 'ip_mudou'
    return True, ''