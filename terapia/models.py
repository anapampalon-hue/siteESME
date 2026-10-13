from django.db import models
from django.contrib.auth.models import User


class Fisioterapeuta(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    nome = models.CharField(max_length=150)
    super_admin = models.BooleanField(default=False)
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return self.nome


class Paciente(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    nome = models.CharField(max_length=150)
    fisioterapeuta = models.ForeignKey(
        Fisioterapeuta, on_delete=models.PROTECT, related_name='pacientes'
    )
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return self.nome


class Exercicio(models.Model):
    nome = models.CharField(max_length=150)
    descricao = models.TextField()
    video_url = models.URLField(blank=True, null=True)
    imagem_url = models.URLField(blank=True, null=True)
    series = models.PositiveIntegerField()
    repeticoes = models.PositiveIntegerField()
    criado_por = models.ForeignKey(Fisioterapeuta, on_delete=models.PROTECT)

    def __str__(self):
        return self.nome


class Prescricao(models.Model):
    paciente = models.ForeignKey(
        Paciente, on_delete=models.CASCADE, related_name='prescricoes'
    )
    exercicio = models.ForeignKey(Exercicio, on_delete=models.PROTECT)
    ordem = models.PositiveIntegerField()
    avancado_de = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='avancados'
    )
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.paciente} — {self.exercicio}"


class Feedback(models.Model):
    prescricao = models.ForeignKey(
        Prescricao, on_delete=models.CASCADE, related_name='feedbacks'
    )
    data = models.DateField(auto_now_add=True)
    dor = models.PositiveIntegerField(null=True, blank=True)
    concluiu = models.BooleanField(default=False)
    pulou = models.BooleanField(default=False)


class Observacao(models.Model):
    paciente = models.ForeignKey(
        Paciente, on_delete=models.CASCADE, related_name='observacoes'
    )
    fisioterapeuta = models.ForeignKey(Fisioterapeuta, on_delete=models.PROTECT)
    texto = models.TextField()
    data = models.DateTimeField(auto_now_add=True)