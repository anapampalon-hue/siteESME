from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('sessao/nova/', views.nova_sessao, name='nova_sessao'),
    path('sessao/espera/', views.espera_mesa, name='espera_mesa'),
    path('sessao/', views.sessao, name='sessao'),
    path('historico/', views.historico, name='historico'),
    path('configuracoes/', views.configuracoes, name='configuracoes'),
    path('sobre/', views.sobre, name='sobre'),
    path('equipe/', views.equipe, name='equipe'),
    path('equipe/novo/', views.equipe_novo, name='equipe_novo'),
    path('equipe/<int:pk>/', views.equipe_perfil, name='equipe_perfil'),
    path('equipe/<int:pk>/senha/', views.equipe_senha, name='equipe_senha'),
    path('equipe/<int:pk>/ativo/', views.equipe_ativo, name='equipe_ativo'),
    path('equipe/<int:pk>/excluir/', views.equipe_excluir, name='equipe_excluir'),
    path('sessao/<int:pk>/relatorio/', views.relatorio, name='relatorio'),
    path('sessao/<int:pk>/exportar.csv', views.exportar_csv, name='exportar_csv'),
    path('api/estado/', views.api_estado, name='api_estado'),
    path('api/comando/', views.api_comando, name='api_comando'),
]