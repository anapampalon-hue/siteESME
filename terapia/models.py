from django.db import models
from django.contrib.auth.models import User


class Fisioterapeuta(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    nome = models.CharField(max_length=150)
    super_admin = models.BooleanField(default=False)
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return self.nome


class Sessao(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    nome = models.CharField(max_length=150)
    fisioterapeuta = models.ForeignKey(
        Fisioterapeuta, on_delete=models.PROTECT, related_name='sessao'
    )
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return self.nome

class Tentativas(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    nome = models.CharField(max_length=150)
    sessao = models.ForeignKey(
        Sessao, on_delete=models.PROTECT, related_name='tentativas'
    )
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return self.nome

class Feedback(models.Model):
    tentativa = models.ForeignKey(
        Tentativas, on_delete=models.CASCADE, related_name='feedbacks', null=True, blank=True
    )
    data = models.DateField(auto_now_add=True)
    dor = models.PositiveIntegerField(null=True, blank=True)
    concluiu = models.BooleanField(default=False)
    pulou = models.BooleanField(default=False)
