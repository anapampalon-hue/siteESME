from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import eh_gestor


@login_required
def home(request):
    fisio = getattr(request.user, 'fisioterapeuta', None)
    contexto = {
        # superadmin pode não ter perfil de fisio: cai no nome de usuário
        'nome': fisio.nome if fisio else request.user.get_username(),
        'eh_gestor': eh_gestor(request.user),  # mostra o botão "Equipe"
    }
    return render(request, 'terapia/home.html', contexto)

def nova_sessao(request):
    return render(request, 'terapia/sessao.html')