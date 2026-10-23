from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('sessao/nova/', views.nova_sessao, name='nova_sessao'),
    path('sessao/espera/', views.espera_mesa, name='espera_mesa'),
    path('sessao/', views.sessao, name='sessao'),
    path('historico/', views.historico, name='historico'),
    path('sessao/<int:pk>/relatorio/', views.relatorio, name='relatorio'),
    path('sessao/<int:pk>/exportar.csv', views.exportar_csv, name='exportar_csv'),
    path('api/estado/', views.api_estado, name='api_estado'),
    path('api/comando/', views.api_comando, name='api_comando'),
]