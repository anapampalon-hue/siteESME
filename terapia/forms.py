from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import Fisioterapeuta


class LoginFisioForm(AuthenticationForm):
    """Login em que a fisio ESCOLHE o nome numa lista (só as ativas) e digita a senha."""

    error_messages = {
        'invalid_login': 'Senha incorreta. Se esqueceu, peça uma nova à super fisioterapeuta.',
        'inactive': 'Este acesso está desativado.',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        fisios = Fisioterapeuta.objects.filter(ativo=True).select_related('user')
        escolhas = [('', 'Selecione seu nome')] + [(f.user.username, f.nome) for f in fisios]
        # a lista é montada a cada vez que a tela abre, então "equipe" sempre está atualizada
        self.fields['username'] = forms.ChoiceField(label='Fisioterapeuta', choices=escolhas)
        self.fields['password'].label = 'Senha'