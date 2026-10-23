"""
terapia/models.py — Banco de dados do ESME (v3: nome do paciente criptografado)

Hierarquia (cada seta é uma chave estrangeira):

    User (Django) ─1:1─ Fisioterapeuta ─1:N─ Sessao ─1:N─ Tentativa ─┬─1:N─ EventoBobina
                                                                      └─1:1─ Feedback

O paciente NÃO é uma tabela: a fisio digita nome e data ao iniciar a sessão
(campos paciente_nome e data_sessao). O nome só aparece no relatório; telas de
lista (histórico, admin) mostram apenas as INICIAIS.

Quem é quem:
    superadmin  -> user.is_superuser                      (o grupo; entra pelo /admin)
    super fisio -> Fisioterapeuta.papel == SUPER_FISIO    (vê todas as sessões, exclui sessões, gerencia a equipe)
    fisio       -> Fisioterapeuta.papel == FISIO          (vê só as próprias sessões; não exclui)
"""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .campos import CampoCriptografado

# Regras fixas do jogo (se mudarem, muda só aqui)
TENTATIVAS_POR_SESSAO = 5
TOTAL_BOBINAS = 9  # bobinas 1..8 = checkpoints, bobina 9 = gol

_PARTICULAS = {'de', 'da', 'do', 'das', 'dos', 'e'}


def iniciais(nome):
    """'Maria da Silva' -> 'M.S.'  (usado em listas, para não expor o nome completo)."""
    partes = [p for p in (nome or '').split() if p.lower() not in _PARTICULAS]
    return ''.join(f'{p[0].upper()}.' for p in partes)


# ──────────────────────────────────────────────────────────────
# PERMISSÕES — uma função só decide "quem vê tudo"
# ──────────────────────────────────────────────────────────────
def eh_gestor(user):
    """True para superadmin ou super fisio (acesso a todas as sessões)."""
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    fisio = getattr(user, 'fisioterapeuta', None)
    return bool(fisio and fisio.ativo and fisio.papel == Fisioterapeuta.Papel.SUPER_FISIO)


# ──────────────────────────────────────────────────────────────
# FISIOTERAPEUTA  (perfil ligado ao login do Django)
# ──────────────────────────────────────────────────────────────
class Fisioterapeuta(models.Model):
    class Papel(models.TextChoices):
        SUPER_FISIO = 'super_fisio', 'Super fisioterapeuta'
        FISIO = 'fisio', 'Fisioterapeuta'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='fisioterapeuta'
    )
    nome = models.CharField(max_length=150)  # aparece na lista da tela de login
    papel = models.CharField(max_length=20, choices=Papel.choices, default=Papel.FISIO)
    # "Tirar da equipe" = ativo=False (some do login, mas o histórico dela é mantido)
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'fisioterapeuta'
        verbose_name_plural = 'fisioterapeutas'
        ordering = ['nome']

    def __str__(self):
        return self.nome

    @property
    def eh_super_fisio(self):
        return self.papel == self.Papel.SUPER_FISIO

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # desativar a fisio também bloqueia o login dela
        if self.user.is_active != self.ativo:
            self.user.is_active = self.ativo
            self.user.save(update_fields=['is_active'])


# ──────────────────────────────────────────────────────────────
# SESSÃO  (1 sessão = até 5 tentativas)
# ──────────────────────────────────────────────────────────────
class SessaoQuerySet(models.QuerySet):
    def ativas(self):
        return self.filter(excluida=False)

    def visiveis_para(self, user):
        """Gestor vê todas; fisio vê só as sessões que ela conduziu."""
        if not user.is_authenticated:
            return self.none()
        if eh_gestor(user):
            return self.ativas()
        fisio = getattr(user, 'fisioterapeuta', None)
        if fisio is None or not fisio.ativo:
            return self.none()
        return self.ativas().filter(fisioterapeuta=fisio)


class Sessao(models.Model):
    class Status(models.TextChoices):
        EM_ANDAMENTO = 'em_andamento', 'Em andamento'
        CONCLUIDA = 'concluida', 'Concluída'
        CANCELADA = 'cancelada', 'Cancelada'

    fisioterapeuta = models.ForeignKey(
        Fisioterapeuta, on_delete=models.PROTECT, related_name='sessoes'
    )  # quem conduziu a sessão

    # Digitados pela fisio na tela "Nova sessão" (não existe cadastro de paciente)
    # criptografado no banco (campos.py); listas e admin mostram só as iniciais
    paciente_nome = CampoCriptografado(max_length=150)
    data_sessao = models.DateField(default=timezone.localdate)

    # Pseudônimo do paciente (campos.codigo_paciente): é o que aparece no histórico, no CSV e, por padrão, no relatório
    codigo_paciente = models.CharField(max_length=12, blank=True, db_index=True)
    # Comentário livre da terapeuta (opcional). Criptografado, porque pode citar dados do paciente.
    comentario = CampoCriptografado(blank=True, default='')
    comentario_em = models.DateTimeField(null=True, blank=True)

    # TCLE virtual (Nova sessão): marcado = o paciente declarou que os dados ficam salvos no histórico, pseudonimizados.
    # Não marcado = sessão ANÔNIMA: sem nome, sem data e sem código, não entra no histórico e é apagada ao fechar.
    anonima = models.BooleanField(default=False)
    consentimento_em = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.EM_ANDAMENTO)

    # "Foto" do hardware no momento em que a sessão iniciou
    circuito_ok = models.BooleanField(default=False)        # obrigatório para iniciar
    batedor_conectado = models.BooleanField(default=False)  # se False, sessão fica sem métricas do batedor

    criada_em = models.DateTimeField(auto_now_add=True)
    iniciada_em = models.DateTimeField(null=True, blank=True)
    finalizada_em = models.DateTimeField(null=True, blank=True)

    # Exclusão "lixeira": só o gestor exclui, e o dado ainda pode ser recuperado pelo /admin
    excluida = models.BooleanField(default=False)
    excluida_em = models.DateTimeField(null=True, blank=True)

    objects = SessaoQuerySet.as_manager()

    class Meta:
        verbose_name = 'sessão'
        verbose_name_plural = 'sessões'
        ordering = ['-data_sessao', '-criada_em']

    def __str__(self):
        # só iniciais: o nome completo não vai para listas, logs ou admin
        return f'{self.iniciais_paciente} — {self.data_sessao:%d/%m/%Y}'

    def garantir_codigo(self):
        """Sessões antigas (de antes do pseudônimo) ganham o código na primeira vez que são lidas."""
        if self.anonima:
            return ''                       # sessão anônima não tem código
        if not self.codigo_paciente and self.paciente_nome:
            from .campos import codigo_paciente
            self.codigo_paciente = codigo_paciente(self.fisioterapeuta_id, self.paciente_nome)
            if self.pk:
                self.save(update_fields=['codigo_paciente'])
        return self.codigo_paciente

    @property
    def iniciais_paciente(self):
        return iniciais(self.paciente_nome)

    @property
    def tem_metricas_do_batedor(self):
        return self.batedor_conectado

    @property
    def tentativas_finalizadas(self):
        return self.tentativas.filter(finalizada_em__isnull=False).count()

    @property
    def completa(self):
        """Libera o botão 'Gerar relatório' (5 tentativas finalizadas)."""
        return self.tentativas_finalizadas >= TENTATIVAS_POR_SESSAO

    @property
    def proximo_numero(self):
        """Número da próxima tentativa (reaproveita o número de uma tentativa descartada)."""
        ultimo = self.tentativas.aggregate(m=models.Max('numero'))['m'] or 0
        return ultimo + 1

    def marcar_excluida(self):
        self.excluida = True
        self.excluida_em = timezone.now()
        self.save(update_fields=['excluida', 'excluida_em'])


# ──────────────────────────────────────────────────────────────
# TENTATIVA  (um "arremesso" do alien até o planeta)
# ──────────────────────────────────────────────────────────────
class Tentativa(models.Model):
    class MotivoFim(models.TextChoices):
        GOL = 'gol', 'Atingiu o gol'
        TIMEOUT = 'timeout', 'Disco lento (bobina não atingida em 3 s)'
        SEM_INICIO = 'sem_inicio', 'Disco não chegou a nenhuma bobina'
        INTERROMPIDA = 'interrompida', 'Interrompida (hardware caiu ou sessão encerrada)'

    sessao = models.ForeignKey(Sessao, on_delete=models.CASCADE, related_name='tentativas')
    # sem limite fixo por sessão (modelo do Sandro): a numeração só cresce; tentativa anulada mantém o número
    numero = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    iniciada_em = models.DateTimeField(null=True, blank=True)
    finalizada_em = models.DateTimeField(null=True, blank=True)
    motivo_fim = models.CharField(max_length=20, choices=MotivoFim.choices, blank=True)

    # Desfecho (códigos; a tela escolhe o texto)
    class Resultado(models.TextChoices):
        GOL = 'gol', 'Gol'
        PAROU = 'parou', 'Parou'
        INTERROMPIDA = 'interrompida', 'Interrompida'

    resultado = models.CharField(max_length=15, choices=Resultado.choices, blank=True)
    motivo = models.CharField(max_length=20, blank=True)   # nova_tentativa | nova_sessao | mesa_reiniciou (só se interrompida)
    anulada = models.BooleanField(default=False)            # reversível; fora dos totais e do PDF
    fluidez_nivel = models.CharField(max_length=15, blank=True)   # alta | media | baixa | indisponivel
    fluidez_motivo = models.CharField(max_length=30, blank=True)  # só se indisponivel
    curva = models.JSONField(null=True, blank=True)               # {"pontos": [[t_s, v_m_s], ...], "v_max": ...} p/ o Detalhe

    # Alcance: 0 = nenhuma bobina · 1..8 = bobina mais alta cruzada · 9 = gol
    bobinas_atingidas = models.PositiveSmallIntegerField(
        default=0, validators=[MaxValueValidator(TOTAL_BOBINAS)]
    )
    tempo_total_ms = models.PositiveIntegerField(null=True, blank=True)
    velocidade_media_cm_s = models.FloatField(null=True, blank=True)
    velocidade_pico_cm_s = models.FloatField(null=True, blank=True)

    # Métricas do batedor (acelerômetro) — ficam vazias se o batedor não estava conectado
    batedor_ok = models.BooleanField(default=False)
    aceleracao_pico_ms2 = models.FloatField(null=True, blank=True)
    aceleracao_media_ms2 = models.FloatField(null=True, blank=True)
    amostras_batedor = models.JSONField(null=True, blank=True)  # [[t_ms, ax, ay, az], ...]

    class Meta:
        ordering = ['sessao', 'numero']
        constraints = [
            models.UniqueConstraint(fields=['sessao', 'numero'], name='tentativa_unica_por_sessao'),
        ]

    def __str__(self):
        return f'Tentativa {self.numero} — {self.sessao}'

    @property
    def chegou_ao_gol(self):
        return self.motivo_fim == self.MotivoFim.GOL

    @property
    def em_andamento(self):
        return self.iniciada_em is not None and self.finalizada_em is None

    @property
    def pode_descartar(self):
        """A fisio só pode descartar tentativa finalizada em que o disco não tocou nenhuma bobina
        (provável erro). A view descartar apaga a tentativa; o número é reaproveitado."""
        return self.finalizada_em is not None and self.bobinas_atingidas == 0


# ──────────────────────────────────────────────────────────────
# EVENTO DE BOBINA  (cada vez que o disco cruza uma bobina)
# ──────────────────────────────────────────────────────────────
class EventoBobina(models.Model):
    tentativa = models.ForeignKey(Tentativa, on_delete=models.CASCADE, related_name='eventos')
    bobina = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(TOTAL_BOBINAS)]
    )
    tempo_ms = models.PositiveIntegerField(help_text='ms desde que a ESP32 armou a tentativa (relógio dela)')

    class Meta:
        ordering = ['tentativa', 'tempo_ms']
        constraints = [
            # o LED fica "travado" aceso, então cada bobina conta uma única vez por tentativa
            models.UniqueConstraint(fields=['tentativa', 'bobina'], name='bobina_unica_por_tentativa'),
        ]

    def __str__(self):
        return f'Bobina {self.bobina} @ {self.tempo_ms} ms'


# ──────────────────────────────────────────────────────────────
# FEEDBACK  (preenchido pela fisio após a tentativa)
# ──────────────────────────────────────────────────────────────
class Feedback(models.Model):
    tentativa = models.OneToOneField(Tentativa, on_delete=models.CASCADE, related_name='feedback')
    data = models.DateField(auto_now_add=True)
    dor = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(10)], help_text='Escala 0 a 10'
    )
    concluiu = models.BooleanField(default=False)
    pulou = models.BooleanField(default=False)

    def __str__(self):
        return f'Feedback — {self.tentativa}'