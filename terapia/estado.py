"""
estado.py — o "programa" do escopo do Sandro, dentro do Django.

Guarda NA MEMÓRIA (um processo só) o que o circuito está fazendo agora:
  * a última vez que a mesa e o batedor deram sinal (sem sinal = ~2 s sem pacotes);
  * se há uma sessão esperando o aperto de 3 s da mesa ("aguardando_mesa");
  * qual é a sessão em andamento (ou encerrada, em leitura).
Sessão e tentativas ficam no banco (models.py). Quem recebe os pacotes é o receptor.py; quem pergunta o
estado é a tela (views.api_estado).

Telas (campo "tela"): sem_sessao | aguardando_mesa | sessao_em_andamento | sessao_encerrada

Tentativa (escopo do Sandro, seção 8.2):
  evento 1 (iniciada)  -> nova linha "aguardando_disco" (se havia outra aberta, ela fecha como interrompida)
  evento 2 (bobina n)  -> "em_andamento"; alcance = bobina mais alta cruzada
  evento 3 (gol)       -> alcance = gol (76 cm)
  evento 4 (fim)       -> "concluida", com resultado gol | parou | interrompida (+ motivo)
Fluidez (escopo 9.2): calculada em SEGUNDO PLANO por fluidez.py. Ao fim da tentativa ela aparece como
"calculando" até chegarem as amostras do batedor que cobrem o fim (ou 3 s); a próxima tentativa já pode rodar.
"""
import collections
import threading
import time
import traceback
import unicodedata
import uuid

from django.utils import timezone

from . import fluidez as calculo_fluidez
from .campos import codigo_paciente, normalizar_nome
from .models import EventoBobina, Fisioterapeuta, Sessao, Tentativa, eh_gestor
from .protocolo import EV_BOBINA, EV_FIM, EV_GOL, EV_INICIO

SEM_SINAL_S = 2.0   # escopo do Sandro: ~2 s sem pacotes = sem sinal
BOBINAS_CM = [20, 27, 34, 41, 48, 55, 62, 69]
GOL_CM = 76
PRAZO_CALCULO_S = 3.0   # escopo: espera as amostras do batedor por até ~3 s
COMENTARIO_MAX = 2000   # letras do comentário da terapeuta
COD_GOL = 9         # Tentativa.bobinas_atingidas == 9 significa "chegou ao gol"


def _sem_acento(txt):
    return ''.join(c for c in unicodedata.normalize('NFD', txt or '') if unicodedata.category(c) != 'Mn').lower().strip()


def _data_iso_valida(txt):
    import datetime
    try:
        d = datetime.date.fromisoformat(txt)
    except (TypeError, ValueError):
        return None
    return d if d.year >= 2000 else None


def _alcance(t):
    b = t.bobinas_atingidas
    if b == COD_GOL:
        return {'cm': GOL_CM, 'bobina': None, 'gol': True}
    if b >= 1:
        return {'cm': BOBINAS_CM[b - 1], 'bobina': b, 'gol': False}
    return {'cm': None, 'bobina': None, 'gol': False}


def _tentativa_dict(t, calculando=False):
    """Uma tentativa no formato do contrato (seção 12.3). A tela só mostra; nunca recalcula.
    estado: aguardando_disco | em_andamento | calculando (fluidez a caminho) | concluida"""
    d = {'numero': t.numero, 'anulada': t.anulada, 'alcance': _alcance(t)}
    if t.finalizada_em is None:
        d['estado'] = 'em_andamento' if t.bobinas_atingidas else 'aguardando_disco'
        return d
    d.update(estado='calculando' if calculando else 'concluida', resultado=t.resultado)
    if t.motivo:
        d['motivo'] = t.motivo
    if calculando:
        return d
    d['fluidez'] = {'nivel': t.fluidez_nivel or 'indisponivel'}
    if d['fluidez']['nivel'] == 'indisponivel':
        d['fluidez']['motivo'] = t.fluidez_motivo or 'nao_calculada'
    return d


def _resumo(tentativas, calculando=()):
    """Totais da sessão: só tentativas concluídas e NÃO anuladas ('fluidez.calculando' = quantas ainda esperam o cálculo)."""
    validas = [t for t in tentativas if t.finalizada_em is not None and not t.anulada]
    fluidez = {'alta': 0, 'media': 0, 'baixa': 0, 'indisponivel': 0, 'calculando': 0}
    for t in validas:
        fluidez['calculando' if t.pk in calculando else (t.fluidez_nivel or 'indisponivel')] += 1
    melhor = {'cm': None, 'bobina': None, 'gol': False}
    if validas:
        m = max(validas, key=lambda t: t.bobinas_atingidas)
        melhor = _alcance(m)
    return {'tentativas_validas': len(validas), 'gols': sum(1 for t in validas if t.resultado == 'gol'),
            'melhor_alcance': melhor, 'fluidez': fluidez}


def _duracao_min(s):
    """Duração em minutos (só se a sessão já tem hora de início e de fim)."""
    if s.iniciada_em and s.finalizada_em:
        return max(0, round((s.finalizada_em - s.iniciada_em).total_seconds() / 60))
    return None


class Programa:
    def __init__(self, relogio=time.monotonic):
        self._lock = threading.RLock()
        self._relogio = relogio
        self.servidor = uuid.uuid4().hex[:8]      # muda quando o servidor reinicia (a tela aceita a versão nova)
        self.versao = 1
        self._rev = 0                             # sobe a cada mudança que a tela precisa ver
        self.mesa_visto = None
        self.batedor_visto = None
        self.mesa = {'boot_id': None, 'contador_sessao': None, 'estado': None}
        self.ev_visto = -1                        # maior ev_id já tratado (descarta repetidos dos "últimos 2 s")
        self.portas = {}                          # porta -> 'livre' | 'ocupada'  (para o Diagnóstico)
        self.espera = None                        # {'fisio_id','paciente','data','base_boot','base_contador'}
        self.sessao_id = None                     # sessão em andamento
        self.leitura_id = None                    # sessão encerrada, ainda na tela (modo leitura)
        self.encerrando = False                   # encerrar pedido com o disco ainda rolando
        self._ultimo = None
        # --- fluidez em segundo plano ---
        self._amostras = collections.deque(maxlen=40000)   # (instante, ax, ay, az) do batedor, ~6 min a 100 Hz
        self._ini = {}                            # pk da tentativa aberta -> instante em que começou
        self._pend = {}                           # pk da tentativa -> {'ini','fim','prazo'} (fluidez a calcular)
        self._ref_repouso = None                  # último repouso do batedor medido nesta sessão
        self._worker = None
        self.calculo_em_segundo_plano = True      # os testes desligam e chamam processar_calculos() à mão

    # ================= entrada: o que o receptor chama =================
    def ao_receber_mesa(self, pacote):
        with self._lock:
            self.mesa_visto = self._relogio()
            if pacote.tipo == 'estado':
                m = self.mesa
                if m['boot_id'] is not None and pacote.boot_id != m['boot_id']:
                    self._mesa_reiniciou(pacote)
                m['boot_id'], m['estado'] = pacote.boot_id, pacote.estado
                m['contador_sessao'] = pacote.contador_sessao
                if self.espera:
                    self._tratar_espera(pacote)
                for ev in sorted(pacote.eventos, key=lambda e: e.ev_id):
                    if ev.ev_id > self.ev_visto:
                        self.ev_visto = ev.ev_id
                        if self.sessao_id:
                            self._tratar_evento(ev)
            self._bump()

    def ao_receber_batedor(self, pacote):
        with self._lock:
            agora = self.batedor_visto = self._relogio()
            if pacote.amostras:
                ultimo = pacote.amostras[-1][1]
                for (_, t_us, ax, ay, az, _gx, _gy, _gz) in pacote.amostras:
                    # o relógio do batedor é outro: ancora a última amostra na hora da chegada do pacote
                    self._amostras.append((agora - ((ultimo - t_us) & 0xFFFFFFFF) / 1e6, ax, ay, az))
            self._bump()

    def _mesa_reiniciou(self, pacote):
        """A mesa ligou de novo: o contador volta a zero (NÃO é um aperto de 3 s) e os ev_id recomeçam."""
        self.ev_visto = -1
        if self.espera:
            self.espera['base_boot'], self.espera['base_contador'] = pacote.boot_id, pacote.contador_sessao
        if self.sessao_id:
            self._fechar_aberta(Tentativa.Resultado.INTERROMPIDA, 'mesa_reiniciou')

    def _tratar_espera(self, pacote):
        e = self.espera
        if e['base_contador'] is None:            # primeiro pacote depois do pedido: define a referência
            e['base_boot'], e['base_contador'] = pacote.boot_id, pacote.contador_sessao
            return
        if pacote.boot_id == e['base_boot'] and pacote.contador_sessao != e['base_contador']:
            # o contador subiu: houve o aperto de 3 s. Eventos que já vieram neste pacote são de ANTES da sessão.
            if pacote.eventos:
                self.ev_visto = max(self.ev_visto, max(ev.ev_id for ev in pacote.eventos))
            self._abrir_sessao()

    # ================= tentativas =================
    def _aberta(self):
        return Tentativa.objects.filter(sessao_id=self.sessao_id, finalizada_em__isnull=True).order_by('-numero').first()

    def _tratar_evento(self, ev):
        if ev.tipo == EV_INICIO:
            self._fechar_aberta(Tentativa.Resultado.INTERROMPIDA, 'nova_tentativa')     # apertou antes do fim
            if self.encerrando:
                return
            n = (Tentativa.objects.filter(sessao_id=self.sessao_id).order_by('-numero').values_list('numero', flat=True).first() or 0) + 1
            nova = Tentativa.objects.create(sessao_id=self.sessao_id, numero=n, iniciada_em=timezone.now())
            self._ini[nova.pk] = self._relogio()
            self._mexeu()
        elif ev.tipo in (EV_BOBINA, EV_GOL):
            t = self._aberta()
            if t is None:
                return
            if ev.tipo == EV_GOL:
                t.bobinas_atingidas = COD_GOL
            elif 1 <= ev.valor <= 8:
                t.bobinas_atingidas = max(t.bobinas_atingidas, ev.valor)    # bobina pulada é aceita
                EventoBobina.objects.get_or_create(tentativa=t, bobina=ev.valor, defaults={'tempo_ms': ev.t_us // 1000})
            t.save(update_fields=['bobinas_atingidas'])
            self._mexeu()
        elif ev.tipo == EV_FIM:
            motivo = {1: 'gol', 2: 'parou', 3: 'nova_tentativa', 4: 'nova_sessao'}.get(ev.valor, 'nova_tentativa')
            if motivo == 'gol':
                self._fechar_aberta(Tentativa.Resultado.GOL, '')
            elif motivo == 'parou':
                self._fechar_aberta(Tentativa.Resultado.PAROU, '')
            else:
                self._fechar_aberta(Tentativa.Resultado.INTERROMPIDA, motivo)

    def _fechar_aberta(self, resultado, motivo):
        t = self._aberta()
        if t is None:
            return
        if resultado == Tentativa.Resultado.GOL:
            t.bobinas_atingidas = COD_GOL
        elif resultado == Tentativa.Resultado.PAROU and t.bobinas_atingidas == 0:
            resultado, motivo = Tentativa.Resultado.INTERROMPIDA, 'nova_tentativa'   # "parou" exige ao menos 1 bobina
        t.resultado, t.motivo = resultado, motivo
        t.finalizada_em = timezone.now()
        t.fluidez_nivel, t.fluidez_motivo = '', ''
        t.save()
        ini, fim = self._ini.pop(t.pk, None), self._relogio()
        if ini is None:                                   # (servidor reiniciou no meio: não há amostras guardadas)
            self._gravar_fluidez(t.pk, {'nivel': 'indisponivel', 'motivo': 'sem_dados_batedor'})
        else:
            self._pend[t.pk] = {'ini': ini, 'fim': fim, 'prazo': fim + PRAZO_CALCULO_S}   # "Calculando fluidez…"
            self._garantir_worker()
        self._mexeu()
        if self.encerrando:
            self._concluir()

    # ================= fluidez em segundo plano =================
    def _garantir_worker(self):
        if self.calculo_em_segundo_plano and self._worker is None:
            self._worker = threading.Thread(target=self._laco_calculo, name='esme-fluidez', daemon=True)
            self._worker.start()

    def _laco_calculo(self):
        """Thread própria: confere a fila a cada 0,2 s e some quando não há mais nada a calcular."""
        try:
            while True:
                time.sleep(0.2)
                try:
                    self.processar_calculos()
                except Exception:
                    traceback.print_exc()
                with self._lock:
                    if not self._pend:
                        self._worker = None
                        return
        finally:
            from django.db import connections
            connections.close_all()

    def processar_calculos(self):
        """Calcula a fluidez das tentativas em espera cujas amostras já chegaram (ou cujo prazo de 3 s acabou).
        A conta roda FORA do lock: o receptor e a tela não esperam por ela."""
        agora = self._relogio()
        with self._lock:
            ultimo = self._amostras[-1][0] if self._amostras else None
            prontos = []
            for pk, p in list(self._pend.items()):
                if (ultimo is not None and ultimo >= p['fim']) or agora >= p['prazo']:
                    janela = [a for a in self._amostras if p['ini'] <= a[0] <= p['fim']]
                    prontos.append((pk, janela, self._ref_repouso))
        for pk, janela, ref in prontos:
            resultado = calculo_fluidez.calcular(janela, ref)
            with self._lock:
                self._gravar_fluidez(pk, resultado)

    def _gravar_fluidez(self, pk, r):
        self._pend.pop(pk, None)
        if r.get('repouso'):
            self._ref_repouso = r['repouso']
        n = Tentativa.objects.filter(pk=pk).update(
            fluidez_nivel=r['nivel'], fluidez_motivo=r.get('motivo', ''), curva=r.get('curva'))
        if n:
            self._mexeu()

    # ================= comandos (vindos da tela) =================
    def preparar_sessao(self, user, paciente, data_iso):
        with self._lock:
            fisio = getattr(user, 'fisioterapeuta', None)
            if fisio is None or not fisio.ativo:
                return {'ok': False, 'erro': 'sem_perfil'}
            if self.espera or self.sessao_id:
                return {'ok': False, 'erro': 'sessao_aberta'}
            paciente = ' '.join((paciente or '').split())
            if not paciente:
                return {'ok': False, 'erro': 'paciente_vazio'}
            if len(paciente) > 150:
                return {'ok': False, 'erro': 'paciente_longo'}
            d = _data_iso_valida(data_iso)
            if d is None:
                return {'ok': False, 'erro': 'data_invalida'}
            conhecido = self.mesa['contador_sessao'] is not None and self._equip(self.mesa_visto) == 'ok'
            self.leitura_id = None
            self.espera = {
                'fisio_id': fisio.pk, 'paciente': paciente, 'data': d,
                'base_boot': self.mesa['boot_id'] if conhecido else None,
                'base_contador': self.mesa['contador_sessao'] if conhecido else None,
            }
            self._mexeu()
            return {'ok': True}

    def cancelar_espera(self, user):
        with self._lock:
            if self.espera and self._eh_dono(user, self.espera['fisio_id']):
                self.espera = None
                self._mexeu()
            return {'ok': True}

    def encerrar_sessao(self, user):
        with self._lock:
            s = Sessao.objects.filter(pk=self.sessao_id).first() if self.sessao_id else None
            if s is None:
                return {'ok': False, 'erro': 'nao_encontrado'}
            if not self._eh_dono(user, s.fisioterapeuta_id):
                return {'ok': False, 'erro': 'sem_permissao'}
            t = self._aberta()
            if t is not None and t.bobinas_atingidas == 0:
                t.delete()                        # a que aguarda o disco é descartada
                t = None
            if t is not None:
                self.encerrando = True            # disco ainda rolando: "Encerrando…" até a tentativa fechar
                self._mexeu()
            else:
                self._concluir()
            return {'ok': True}

    def _concluir(self):
        s = Sessao.objects.filter(pk=self.sessao_id).first()
        self.encerrando = False
        if s is not None:
            if s.tentativas.filter(finalizada_em__isnull=False).exists():
                s.status, s.finalizada_em = Sessao.Status.CONCLUIDA, timezone.now()
                s.save(update_fields=['status', 'finalizada_em'])
                self.leitura_id = s.pk
            else:
                s.delete()                        # sessão sem tentativas não é salva
        self.sessao_id = None
        self._mexeu()

    def _marcar(self, user, numero, anulada):
        with self._lock:
            sid = self.sessao_id or self.leitura_id
            t = Tentativa.objects.filter(sessao_id=sid, numero=numero, finalizada_em__isnull=False).select_related('sessao').first() if sid else None
            if t is None:
                return {'ok': False, 'erro': 'nao_encontrado'}
            if not self._eh_dono(user, t.sessao.fisioterapeuta_id):
                return {'ok': False, 'erro': 'sem_permissao'}
            t.anulada = anulada
            t.save(update_fields=['anulada'])
            self._mexeu()
            return {'ok': True}

    def anular(self, user, numero):
        return self._marcar(user, numero, True)

    def restaurar(self, user, numero):
        return self._marcar(user, numero, False)

    def obter_curva(self, user, numero):
        """Curva de velocidade da tentativa, para o Detalhe. A escala é a MESMA em todas as tentativas da sessão
        (escopo 9.2: o que se compara é a forma). curva = None quando não há (fluidez indisponível ou ainda calculando)."""
        with self._lock:
            sid = self.sessao_id or self.leitura_id
            t = Tentativa.objects.filter(sessao_id=sid, numero=numero, finalizada_em__isnull=False).select_related('sessao').first() if sid else None
            if t is None:
                return {'ok': False, 'erro': 'nao_encontrado'}
            if not self._pode_ver(user, t.sessao.fisioterapeuta_id):
                return {'ok': False, 'erro': 'sem_permissao'}
            if not t.curva or t.pk in self._pend:
                return {'ok': True, 'curva': None}
            todas = Tentativa.objects.filter(sessao_id=sid, curva__isnull=False).values_list('curva', flat=True)
            escala = max((c.get('v_max', 0) for c in todas if c), default=t.curva['v_max'])
            return {'ok': True, 'curva': {'pontos': t.curva['pontos'], 'escala_max': escala}}

    # ================= comentário, histórico e sessões antigas =================
    def salvar_comentario(self, user, texto):
        """Comentário livre e OPCIONAL da terapeuta, na sessão aberta ou numa sessão aberta do histórico."""
        with self._lock:
            sid = self.sessao_id or self.leitura_id
            s = Sessao.objects.filter(pk=sid).first() if sid else None
            if s is None:
                return {'ok': False, 'erro': 'nao_encontrado'}
            if not self._eh_dono(user, s.fisioterapeuta_id):
                return {'ok': False, 'erro': 'sem_permissao'}
            texto = (texto or '').replace('\r\n', '\n').strip()
            if len(texto) > COMENTARIO_MAX:
                return {'ok': False, 'erro': 'comentario_longo'}
            s.comentario = texto
            s.comentario_em = timezone.now() if texto else None
            s.save(update_fields=['comentario', 'comentario_em'])
            return {'ok': True}

    def abrir_sessao(self, user, pk):
        """Abre uma sessão do histórico na tela de Sessão (só leitura, com Detalhes, Anular e comentário)."""
        with self._lock:
            if self.espera or self.sessao_id:
                return {'ok': False, 'erro': 'sessao_aberta'}
            s = Sessao.objects.visiveis_para(user).filter(pk=pk).first()
            if s is None:
                return {'ok': False, 'erro': 'nao_encontrado'}
            self.leitura_id = s.pk
            self._mexeu()
            return {'ok': True}

    def concluir_interrompida(self, user):
        """"Encerrar" de uma sessão interrompida (o programa foi fechado): só troca o status para concluída."""
        with self._lock:
            s = Sessao.objects.filter(pk=self.leitura_id).first() if self.leitura_id else None
            if s is None or s.status != Sessao.Status.EM_ANDAMENTO:
                return {'ok': False, 'erro': 'nao_encontrado'}
            if not self._eh_dono(user, s.fisioterapeuta_id):
                return {'ok': False, 'erro': 'sem_permissao'}
            ultima = s.tentativas.filter(finalizada_em__isnull=False).order_by('-finalizada_em').first()
            if ultima is None:
                s.delete()                          # sem tentativas não se guarda
                self.leitura_id = None
            else:
                s.status, s.finalizada_em = Sessao.Status.CONCLUIDA, ultima.finalizada_em   # hora do fim = última tentativa gravada
                s.save(update_fields=['status', 'finalizada_em'])
            self._mexeu()
            return {'ok': True}

    def listar_historico(self, user, busca='', data_iso='', revelar=False):
        """Lista de sessões (mais recente primeiro). O nome só vai junto se `revelar` — o padrão é só o código pseudônimo."""
        with self._lock:
            pre = normalizar_nome(busca)
            alvo = _data_iso_valida(data_iso) if data_iso else None
            linhas = []
            for s in Sessao.objects.visiveis_para(user).select_related('fisioterapeuta').order_by('-iniciada_em', '-criada_em'):
                if s.pk == self.sessao_id:
                    continue                        # a sessão em andamento não é histórico ainda
                tents = list(s.tentativas.all())
                finais = [t for t in tents if t.finalizada_em is not None]
                if not finais:
                    continue                        # sessão sem tentativas não aparece
                if alvo and s.data_sessao != alvo:
                    continue
                nome = s.paciente_nome or ''
                codigo = s.garantir_codigo()
                if pre and pre not in normalizar_nome(nome) and pre not in codigo.lower().replace('-', '') and pre not in codigo.lower():
                    continue
                validas = [t for t in finais if not t.anulada]
                melhor = _alcance(max(validas, key=lambda t: t.bobinas_atingidas)) if validas else {'cm': None, 'bobina': None, 'gol': False}
                linha = {
                    'id': s.pk, 'codigo': codigo, 'data': s.data_sessao.isoformat(),
                    'inicio': s.iniciada_em.isoformat() if s.iniciada_em else None,
                    'tentativas_validas': len(validas), 'melhor_alcance': melhor,
                    'status': 'interrompida' if s.status == Sessao.Status.EM_ANDAMENTO else 'concluida',
                    'tem_comentario': bool(s.comentario),
                }
                if revelar:
                    linha['nome'] = nome
                if eh_gestor(user):
                    linha['fisio'] = s.fisioterapeuta.nome
                linhas.append(linha)
                if len(linhas) >= 300:
                    break
            return {'ok': True, 'sessoes': linhas}

    def fechar_leitura(self, user):
        with self._lock:
            self.leitura_id = None
            self._mexeu()
            return {'ok': True}

    def sugestoes_nome(self, user, prefixo):
        fisio = getattr(user, 'fisioterapeuta', None)
        pre = _sem_acento(prefixo)
        if fisio is None or not pre:
            return {'ok': True, 'nomes': []}
        # o nome é criptografado no banco, então o filtro é feito aqui, depois de ler (poucos registros por fisio)
        vistos = {}
        for nome in Sessao.objects.ativas().filter(fisioterapeuta=fisio).values_list('paciente_nome', flat=True):
            if _sem_acento(nome).startswith(pre):
                vistos.setdefault(_sem_acento(nome), nome)
        return {'ok': True, 'nomes': sorted(vistos.values(), key=_sem_acento)[:6]}

    # ================= saída: o estado que a tela lê =================
    def _sessao_dict(self, s, status):
        tents = list(s.tentativas.order_by('-numero'))
        return {
            'id': s.pk, 'codigo': s.garantir_codigo(), 'comentario': s.comentario or '',
            'paciente': s.paciente_nome, 'data': s.data_sessao.isoformat(),
            'inicio': s.iniciada_em.isoformat() if s.iniciada_em else None,
            'fim': s.finalizada_em.isoformat() if s.finalizada_em else None,
            'status': status, 'duracao_min': _duracao_min(s), 'tentativas': [_tentativa_dict(t, t.pk in self._pend) for t in tents],
            'resumo': _resumo(tents, self._pend),
            'pdf': None, 'encerrando': self.encerrando and status == 'em_andamento',
        }

    def snapshot(self, user):
        with self._lock:
            self._bump()      # atualiza a versão se alguma placa ficou sem sinal
            fisio = getattr(user, 'fisioterapeuta', None)
            nome = fisio.nome if fisio else user.get_username()
            tela, sessao = 'sem_sessao', None
            if self.espera and self._eh_dono(user, self.espera['fisio_id']):
                tela = 'aguardando_mesa'
                sessao = {'paciente': self.espera['paciente'], 'data': self.espera['data'].isoformat()}
            else:
                for sid, tela_s, status in ((self.sessao_id, 'sessao_em_andamento', 'em_andamento'),
                                            (self.leitura_id, 'sessao_encerrada', 'concluida')):
                    s = Sessao.objects.filter(pk=sid).first() if sid else None
                    if s and self._pode_ver(user, s.fisioterapeuta_id):
                        if tela_s == 'sessao_encerrada' and s.status == Sessao.Status.EM_ANDAMENTO:
                            status = 'interrompida'      # o programa foi fechado no meio dela
                        tela, sessao = tela_s, self._sessao_dict(s, status)
                        break
            return {
                'versao': self.versao, 'servidor': self.servidor, 'tela': tela,
                'conta': {'nome': nome},
                'equipamentos': {'mesa': self._equip(self.mesa_visto), 'batedor': self._equip(self.batedor_visto)},
                'sessao': sessao,
            }

    # ================= internos =================
    def _equip(self, visto):
        return 'ok' if visto is not None and self._relogio() - visto <= SEM_SINAL_S else 'sem_sinal'

    def _eh_dono(self, user, fisio_id):
        fisio = getattr(user, 'fisioterapeuta', None)
        return bool(fisio and fisio.pk == fisio_id) or user.is_superuser

    def _pode_ver(self, user, fisio_id):
        """Ler uma sessão (histórico, curva, relatório): a dona da sessão e o gestor."""
        return self._eh_dono(user, fisio_id) or eh_gestor(user)

    def _mexeu(self):
        self._rev += 1
        self._bump()

    def _bump(self):
        """Aumenta a versão quando algo que a tela mostra mudou."""
        chave = (self._equip(self.mesa_visto), self._equip(self.batedor_visto), self._rev)
        if chave != self._ultimo:
            self._ultimo = chave
            self.versao += 1

    def _abrir_sessao(self):
        e = self.espera
        fisio = Fisioterapeuta.objects.get(pk=e['fisio_id'])
        s = Sessao.objects.create(
            fisioterapeuta=fisio, paciente_nome=e['paciente'], data_sessao=e['data'],
            codigo_paciente=codigo_paciente(fisio.pk, e['paciente']),
            status=Sessao.Status.EM_ANDAMENTO, circuito_ok=True,
            batedor_conectado=self._equip(self.batedor_visto) == 'ok',
            iniciada_em=timezone.now(),   # a hora do aperto de 3 s é a hora de início (escopo 7.6)
        )
        self.sessao_id, self.espera, self.encerrando = s.pk, None, False
        self._ref_repouso = None
        self._mexeu()


programa = Programa()