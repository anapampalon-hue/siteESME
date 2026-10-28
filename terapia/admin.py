from django.contrib import admin

from .models import EventoBobina, Feedback, Fisioterapeuta, Sessao, Tentativa


class TentativaInline(admin.TabularInline):
    model = Tentativa
    extra = 0
    show_change_link = True
    fields = ('numero', 'motivo_fim', 'bobinas_atingidas', 'tempo_total_ms', 'batedor_ok')
    readonly_fields = fields
    can_delete = False


class EventoBobinaInline(admin.TabularInline):
    model = EventoBobina
    extra = 0


@admin.register(Fisioterapeuta)
class FisioterapeutaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'papel', 'ativo')
    list_filter = ('papel', 'ativo')


@admin.register(Sessao)
class SessaoAdmin(admin.ModelAdmin):
    # Listas mostram só as INICIAIS; o nome completo fica na página de edição/relatório
    list_display = ('iniciais_paciente', 'data_sessao', 'fisioterapeuta', 'status', 'batedor_conectado', 'excluida')
    list_filter = ('status', 'excluida', 'fisioterapeuta')
    date_hierarchy = 'data_sessao'
    inlines = [TentativaInline]

    @admin.display(description='Paciente (iniciais)')
    def iniciais_paciente(self, obj):
        return obj.iniciais_paciente


@admin.register(Tentativa)
class TentativaAdmin(admin.ModelAdmin):
    list_display = ('sessao', 'numero', 'motivo_fim', 'bobinas_atingidas', 'tempo_total_ms')
    inlines = [EventoBobinaInline]


admin.site.register(Feedback)