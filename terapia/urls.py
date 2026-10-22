from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('sessao/nova/', views.nova_sessao, name='nova_sessao'),
    path('sessao/espera/', views.espera_mesa, name='espera_mesa'),
    path('sessao/', views.sessao, name='sessao'),
    path('api/estado/', views.api_estado, name='api_estado'),
    path('api/comando/', views.api_comando, name='api_comando'),
]