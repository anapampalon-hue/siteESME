"""
diagnostico.py — descobre por que as bolinhas não ficam verdes.
Rode na pasta do projeto (onde está o manage.py), COM o servidor (runserver) ligado:
    python tools\\diagnostico.py
Ele não muda nada; só confere e mostra o que está certo (OK) e o que está errado (FALTA).
"""
import os
import socket
import struct
import sys
import urllib.request

raiz = os.getcwd()
print('Pasta:', raiz)
ok = lambda c, t: print(('  OK     ' if c else '  FALTA  ') + t) or c

print('\n1) Arquivos no lugar')
for rel in ['manage.py', 'terapia/apps.py', 'terapia/receptor.py', 'terapia/estado.py', 'terapia/protocolo.py',
            'terapia/campos.py', 'terapia/static/terapia/js/dados.js', 'terapia/static/terapia/js/nova_sessao.js',
            'terapia/static/terapia/js/textos.js']:
    ok(os.path.exists(os.path.join(raiz, *rel.split('/'))), rel)
try:
    ap = open(os.path.join(raiz, 'terapia', 'apps.py'), encoding='utf-8').read()
    ok('receptor.iniciar' in ap, 'apps.py é a versão nova (liga o receptor UDP)')
except OSError:
    pass

print('\n2) O servidor está ouvindo as portas das placas?  (se estiver, elas aparecem "ocupadas" aqui, e isso é BOM)')
for nome, porta in (('mesa', 4212), ('batedor', 4210)):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(('0.0.0.0', porta))
        ok(False, f'porta {porta} ({nome}) está LIVRE: o receptor do site NÃO está rodando')
    except OSError:
        ok(True, f'porta {porta} ({nome}) está em uso: o receptor do site está ouvindo')
    finally:
        s.close()

print('\n3) O site responde?')
try:
    r = urllib.request.urlopen('http://127.0.0.1:8000/accounts/login/', timeout=3)
    ok(r.status == 200, 'site responde em 127.0.0.1:8000')
except Exception as e:
    ok(False, f'site NÃO responde em 127.0.0.1:8000 ({e}). Ligue o runserver.')

print('\n4) Mandando 1 pacote de teste para a mesa e outro para o batedor')
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.sendto(struct.pack('<II', 1, 1000), ('127.0.0.1', 4212))
s.sendto(struct.pack('<HBB', 1, 1, 4) + struct.pack('<IIhhhhhh', 1, 1000, 0, 0, 2048, 0, 0, 0), ('127.0.0.1', 4210))
print('  enviado. No terminal do servidor deve aparecer "[ESME] Primeiro pacote recebido na porta ...".')
print('\nMande o resultado (OK/FALTA) para quem está te ajudando.')