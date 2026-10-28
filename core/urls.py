"""URLs do projeto ESME."""
from django.contrib import admin
from django.contrib.auth.views import LoginView
from django.urls import include, path

from terapia.forms import LoginFisioForm

urlpatterns = [
    path('admin/', admin.site.urls),
    # login com LISTA DE NOMES (precisa vir antes do include das urls de auth)
    path(
        'accounts/login/',
        LoginView.as_view(authentication_form=LoginFisioForm, redirect_authenticated_user=True),
        name='login',
    ),
    path('accounts/', include('django.contrib.auth.urls')),  # logout, etc.
    path('', include('terapia.urls')),
]