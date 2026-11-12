"""
tests.py — testes da avaliação das tentativas, do MRC e da exclusão de sessões.

Rodar:  python manage.py test terapia
(cada teste usa um banco temporário: o db.sqlite3 de vocês não é tocado)
"""
import json
import os

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

# chaves só para os testes (a pasta dados_privados/ não é criada nem lida)
os.environ.setdefault('ESME_CHAVE', Fernet.generate_key().decode())
os.environ.setdefault('ESME_CHAVE_PSEUDO', 'chave-de-teste-nao-usar-em-producao')

from . import estado, views  # noqa: E402
from .models import Feedback, Fisioterapeuta, MrcItem, Sessao, Tentativa  # noqa: E402

User = get_user_model()


def _fisio(username, papel=Fisioterapeuta.Papel.FISIO):
    u = User.objects.create_user(username, password='x')
    return u, Fisioterapeuta.objects.create(user=u, nome=username, papel=papel)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])   # deixa os testes rápidos
class Base(TestCase):
    def setUp(self):
        self.prog = estado.Programa()
        self.prog.calculo_em_segundo_plano = False
        self.u1, self.f1 = _fisio('ana')
        self.u2, self.f2 = _fisio('bia')
        self.sup, self.fsup = _fisio('sup', Fisioterapeuta.Papel.SUPER_FISIO)
        self.s = Sessao.objects.create(fisioterapeuta=self.f1, paciente_nome='Maria Silva', status=Sessao.Status.EM_ANDAMENTO)
        self.prog.sessao_id = self.s.pk

    def tentativa(self, numero, resultado='parou', anulada=False, concluida=True):
        return Tentativa.objects.create(
            sessao=self.s, numero=numero, bobinas_atingidas=2 if resultado != 'interrompida' else 0,
            resultado=resultado if concluida else '', anulada=anulada,
            finalizada_em=timezone.now() if concluida else None)


class AvaliacaoTests(Base):
    def test_salva_qualidade_dor_e_nota(self):
        self.tentativa(1)
        self.assertTrue(self.prog.salvar_avaliacao(self.u1, 1, {'qualidade': 4})['ok'])
        self.assertTrue(self.prog.salvar_avaliacao(self.u1, 1, {'dor': 1, 'nota': 'cansou no fim'})['ok'])
        fb = Feedback.objects.get(tentativa__numero=1)
        self.assertEqual((fb.qualidade, fb.dor, fb.nota), (4, 1, 'cansou no fim'))

    def test_nota_fica_criptografada_no_banco(self):
        self.tentativa(1)
        self.prog.salvar_avaliacao(self.u1, 1, {'nota': 'texto secreto'})
        with connection.cursor() as c:
            c.execute('SELECT nota FROM terapia_feedback')
            bruto = c.fetchone()[0]
        self.assertNotIn('secreto', bruto)
        self.assertTrue(bruto.startswith('gAAAA'))

    def test_qualidade_pode_voltar_ao_branco(self):
        self.tentativa(1)
        self.prog.salvar_avaliacao(self.u1, 1, {'qualidade': 3})
        self.prog.salvar_avaliacao(self.u1, 1, {'qualidade': None})
        self.assertIsNone(Feedback.objects.get().qualidade)

    def test_valores_invalidos_sao_recusados(self):
        self.tentativa(1)
        for campos in ({'qualidade': 6}, {'qualidade': -1}, {'dor': 3}, {'dor': True}, {'qualidade': '4'}, {'nota': 5}):
            self.assertFalse(self.prog.salvar_avaliacao(self.u1, 1, campos)['ok'], campos)
        self.assertEqual(self.prog.salvar_avaliacao(self.u1, 1, {'nota': 'x' * (estado.NOTA_MAX + 1)})['erro'], 'nota_longa')
        self.assertFalse(Feedback.objects.exists())

    def test_interrompida_nao_e_avaliada(self):
        self.tentativa(1, 'interrompida')
        self.assertEqual(self.prog.salvar_avaliacao(self.u1, 1, {'dor': 0})['erro'], 'tentativa_interrompida')

    def test_outra_terapeuta_nao_avalia(self):
        self.tentativa(1)
        self.assertEqual(self.prog.salvar_avaliacao(self.u2, 1, {'dor': 0})['erro'], 'sem_permissao')

    def test_snapshot_traz_avaliacao_e_pendencias(self):
        self.tentativa(1)
        self.tentativa(2)
        self.tentativa(3, 'interrompida')
        self.tentativa(4, anulada=True)
        snap = self.prog.snapshot(self.u1)['sessao']
        self.assertEqual(snap['avaliacoes_pendentes'], 2)          # só 1 e 2 contam
        self.prog.salvar_avaliacao(self.u1, 1, {'dor': 0})
        sessao = self.prog.snapshot(self.u1)['sessao']
        self.assertEqual(sessao['avaliacoes_pendentes'], 1)
        t1 = next(t for t in sessao['tentativas'] if t['numero'] == 1)
        self.assertEqual(t1['avaliacao'], {'qualidade': None, 'dor': 0, 'nota': ''})


class EncerrarTests(Base):
    def test_encerrar_recusa_enquanto_falta_dor(self):
        self.tentativa(1)
        self.tentativa(2)
        r = self.prog.encerrar_sessao(self.u1)
        self.assertEqual((r['ok'], r['erro'], r['pendentes']), (False, 'avaliacoes_pendentes', 2))
        self.prog.salvar_avaliacao(self.u1, 1, {'dor': 0})
        self.assertEqual(self.prog.encerrar_sessao(self.u1)['pendentes'], 1)
        self.s.refresh_from_db()
        self.assertEqual(self.s.status, Sessao.Status.EM_ANDAMENTO)

    def test_encerra_quando_a_dor_esta_preenchida(self):
        self.tentativa(1)
        self.tentativa(2, 'interrompida')       # não conta
        self.tentativa(3, anulada=True)         # não conta
        self.prog.salvar_avaliacao(self.u1, 1, {'dor': 2})      # estrelas ficam em branco: tudo bem
        self.assertTrue(self.prog.encerrar_sessao(self.u1)['ok'])
        self.s.refresh_from_db()
        self.assertEqual(self.s.status, Sessao.Status.CONCLUIDA)

    def test_anular_tira_a_obrigacao_e_restaurar_devolve(self):
        self.tentativa(1)
        self.assertFalse(self.prog.encerrar_sessao(self.u1)['ok'])
        self.prog.anular(self.u1, 1)
        self.assertEqual(self.prog.snapshot(self.u1)['sessao']['avaliacoes_pendentes'], 0)
        self.prog.restaurar(self.u1, 1)
        self.assertEqual(self.prog.snapshot(self.u1)['sessao']['avaliacoes_pendentes'], 1)

    def test_sessao_interrompida_tambem_exige_a_dor(self):
        self.tentativa(1)
        self.prog.sessao_id, self.prog.leitura_id = None, self.s.pk
        self.assertEqual(self.prog.concluir_interrompida(self.u1)['erro'], 'avaliacoes_pendentes')
        self.prog.salvar_avaliacao(self.u1, 1, {'dor': 1})
        self.assertTrue(self.prog.concluir_interrompida(self.u1)['ok'])

    def test_encerrando_com_tentativa_rolando_continua_aberta_se_faltar_dor(self):
        self.tentativa(1)
        self.prog.salvar_avaliacao(self.u1, 1, {'dor': 0})
        aberta = Tentativa.objects.create(sessao=self.s, numero=2, bobinas_atingidas=3)
        self.assertTrue(self.prog.encerrar_sessao(self.u1)['ok'])
        self.assertTrue(self.prog.encerrando)
        self.prog._fechar_aberta(Tentativa.Resultado.PAROU, '')           # o disco parou: a nº 2 ainda não tem dor
        self.assertFalse(self.prog.encerrando)
        self.s.refresh_from_db()
        self.assertEqual(self.s.status, Sessao.Status.EM_ANDAMENTO)
        aberta.refresh_from_db()
        self.assertEqual(aberta.resultado, 'parou')


class MrcTests(Base):
    def test_salva_e_devolve(self):
        r = self.prog.salvar_mrc(self.u1, [{'grupo': 'Ombro', 'grau': 4, 'nota': 'ok'}, {'grupo': 'Punho', 'grau': 0}])
        self.assertTrue(r['ok'])
        m = self.prog.snapshot(self.u1)['sessao']['mrc']
        self.assertEqual([(x['grupo'], x['grau'], x['nota']) for x in m], [('Ombro', 4, 'ok'), ('Punho', 0, '')])

    def test_maximo_de_cinco_e_linha_vazia_ignorada(self):
        seis = [{'grupo': f'g{i}', 'grau': 1} for i in range(6)]
        self.assertEqual(self.prog.salvar_mrc(self.u1, seis)['erro'], 'mrc_invalido')
        self.assertTrue(self.prog.salvar_mrc(self.u1, [{'grupo': '', 'grau': None, 'nota': ''}, {'grupo': 'Ombro', 'grau': 3}])['ok'])
        self.assertEqual(MrcItem.objects.count(), 1)

    def test_grau_invalido_e_nota_criptografada(self):
        self.assertFalse(self.prog.salvar_mrc(self.u1, [{'grupo': 'Ombro', 'grau': 6}])['ok'])
        self.prog.salvar_mrc(self.u1, [{'grupo': 'Ombro', 'grau': 3, 'nota': 'segredo'}])
        with connection.cursor() as c:
            c.execute('SELECT nota FROM terapia_mrcitem')
            self.assertNotIn('segredo', c.fetchone()[0])

    def test_outra_terapeuta_nao_mexe(self):
        self.assertEqual(self.prog.salvar_mrc(self.u2, [{'grupo': 'Ombro', 'grau': 3}])['erro'], 'sem_permissao')

    def test_substitui_a_lista_anterior(self):
        self.prog.salvar_mrc(self.u1, [{'grupo': 'A', 'grau': 1}, {'grupo': 'B', 'grau': 2}])
        self.prog.salvar_mrc(self.u1, [{'grupo': 'C', 'grau': 3}])
        self.assertEqual(list(MrcItem.objects.values_list('grupo', flat=True)), ['C'])


class EscalasTests(Base):
    def test_salva_e_devolve(self):
        self.assertTrue(self.prog.salvar_escalas(self.u1, '48', '12,5', '3,5')['ok'])     # texto com vírgula, como se digita
        e = self.prog.snapshot(self.u1)['sessao']['escalas']
        self.assertEqual(e, {'fma': 48, 'wmft_tempo': 12.5, 'wmft_nota': 3.5})

    def test_vazio_limpa(self):
        self.prog.salvar_escalas(self.u1, 30, 10, 2)
        self.assertTrue(self.prog.salvar_escalas(self.u1, '', None, '')['ok'])
        self.assertEqual(self.prog.snapshot(self.u1)['sessao']['escalas'], {'fma': None, 'wmft_tempo': None, 'wmft_nota': None})

    def test_valores_invalidos(self):
        for fma, tempo, nota in [(67, None, None), (-1, None, None), ('4,5', None, None), ('abc', None, None),
                                 (None, 121, 3), (None, 10, 5.1), (None, -2, 1), (True, None, None), (None, 'x', 1)]:
            self.assertEqual(self.prog.salvar_escalas(self.u1, fma, tempo, nota)['erro'], 'escala_invalida', (fma, tempo, nota))

    def test_limites_aceitos(self):
        self.assertTrue(self.prog.salvar_escalas(self.u1, 0, 0, 0)['ok'])
        self.assertTrue(self.prog.salvar_escalas(self.u1, 66, 120, 5)['ok'])

    def test_outra_terapeuta_nao_mexe(self):
        self.assertEqual(self.prog.salvar_escalas(self.u2, 10, None, None)['erro'], 'sem_permissao')

    def test_relatorio_so_com_o_preenchido(self):
        from .exportar import dados_relatorio, gerar_csv
        self.assertEqual(dados_relatorio(self.s)['escalas'], [])
        self.prog.salvar_escalas(self.u1, 48, None, None)
        self.s.refresh_from_db()
        self.assertEqual(dados_relatorio(self.s)['escalas'], [('Fugl-Meyer (membro superior)', '48 de 66')])
        self.prog.salvar_escalas(self.u1, '', 12.5, None)                          # WMFT só com os dois valores
        self.s.refresh_from_db()
        self.assertEqual(dados_relatorio(self.s)['escalas'], [])
        self.prog.salvar_escalas(self.u1, 48, 12.5, 3.5)
        self.s.refresh_from_db()
        nomes = [n for n, _ in dados_relatorio(self.s)['escalas']]
        self.assertEqual(nomes, ['Fugl-Meyer (membro superior)', 'Wolf Motor (WMFT)'])
        self.assertIn('12,5 s', dados_relatorio(self.s)['escalas'][1][1])
        self.assertNotIn('Fugl', gerar_csv(self.s))                                # escalas ficam só no relatório

    def test_comando_http(self):
        antigo = views.programa
        views.programa = self.prog
        try:
            self.client.force_login(self.u1)
            corpo = json.dumps({'nome': 'salvar_escalas', 'args': {'fma': 20}})
            r = self.client.post('/api/comando/', data=corpo, content_type='application/json')
            self.assertTrue(r.json()['ok'])
            self.assertEqual(Sessao.objects.get(pk=self.s.pk).fma_total, 20)
        finally:
            views.programa = antigo


class ExcluirTests(Base):
    def setUp(self):
        super().setUp()
        self.prog.sessao_id = None
        self.s.status = Sessao.Status.CONCLUIDA
        self.s.save()
        self.tentativa(1)
        Feedback.objects.create(tentativa=self.s.tentativas.get(), dor=0)
        MrcItem.objects.create(sessao=self.s, ordem=1, grupo='Ombro', grau=3)

    def test_fisio_comum_nao_exclui(self):
        self.assertEqual(self.prog.excluir_sessao(self.u1, self.s.pk)['erro'], 'sem_permissao')
        self.assertTrue(Sessao.objects.filter(pk=self.s.pk).exists())

    def test_supervisora_exclui_de_vez_com_tudo_que_depende(self):
        self.assertTrue(self.prog.excluir_sessao(self.sup, self.s.pk)['ok'])
        self.assertFalse(Sessao.objects.exists())
        self.assertEqual((Tentativa.objects.count(), Feedback.objects.count(), MrcItem.objects.count()), (0, 0, 0))

    def test_superadmin_tambem_exclui(self):
        admin = User.objects.create_superuser('root', password='x')
        self.assertTrue(self.prog.excluir_sessao(admin, self.s.pk)['ok'])

    def test_nao_exclui_a_sessao_em_andamento(self):
        self.prog.sessao_id = self.s.pk
        self.assertEqual(self.prog.excluir_sessao(self.sup, self.s.pk)['erro'], 'sessao_aberta')

    def test_inexistente(self):
        self.assertEqual(self.prog.excluir_sessao(self.sup, 9999)['erro'], 'nao_encontrado')

    def test_historico_diz_quem_pode_excluir(self):
        self.assertFalse(self.prog.listar_historico(self.u1)['pode_excluir'])
        self.assertTrue(self.prog.listar_historico(self.sup)['pode_excluir'])

    def test_pela_url_a_fisio_comum_tambem_e_recusada(self):
        """O teste que importa: mesmo mandando o pedido na mão, a conta comum não exclui."""
        antigo = views.programa
        views.programa = self.prog
        try:
            corpo = json.dumps({'nome': 'excluir_sessao', 'args': {'id': self.s.pk}})
            self.client.force_login(self.u1)
            r = self.client.post('/api/comando/', data=corpo, content_type='application/json')
            self.assertEqual(r.json(), {'ok': False, 'erro': 'sem_permissao'})
            self.assertTrue(Sessao.objects.filter(pk=self.s.pk).exists())
            self.client.force_login(self.sup)
            r = self.client.post('/api/comando/', data=corpo, content_type='application/json')
            self.assertTrue(r.json()['ok'])
        finally:
            views.programa = antigo


class ExportarTests(Base):
    def test_relatorio_e_csv_levam_avaliacao_e_mrc(self):
        from .exportar import dados_relatorio, gerar_csv
        self.tentativa(1)
        self.tentativa(2)
        self.tentativa(3, resultado='interrompida')
        self.prog.salvar_avaliacao(self.u1, 1, {'qualidade': 4, 'dor': 2, 'nota': 'dor no fim'})
        self.prog.salvar_avaliacao(self.u1, 2, {'dor': 0})            # sem estrelas: ficam as 5 vazias
        self.prog.salvar_mrc(self.u1, [{'grupo': 'Quadríceps', 'grau': 4, 'nota': 'ok'}])
        r = dados_relatorio(self.s)
        t1, t2, t3 = r['tentativas']
        self.assertEqual((t1['aval']['estrelas'], t1['aval']['dor'], t1['aval']['nota']), ('★★★★☆', '2 · pronunciada', 'dor no fim'))
        self.assertEqual((t2['aval']['estrelas'], t2['aval']['dor']), ('☆☆☆☆☆', '0 · nenhuma'))
        self.assertFalse(t3['aval']['avaliavel'])
        self.assertEqual(r['mrc'], [{'grupo': 'Quadríceps', 'grau': 4, 'nota': 'ok'}])
        csv_txt = gerar_csv(self.s)
        self.assertIn('qualidade_movimento;dor', csv_txt)
        self.assertNotIn('dor no fim', csv_txt)                      # anotação livre nunca vai no CSV
        self.assertNotIn('Quadríceps', csv_txt)

    def test_mrc_vazio_nao_aparece(self):
        from .exportar import dados_relatorio
        self.prog.salvar_mrc(self.u1, [{'grupo': '', 'grau': None, 'nota': ''}])
        self.assertEqual(dados_relatorio(self.s)['mrc'], [])


class TransferirTests(Base):
    def setUp(self):
        super().setUp()
        self.prog.sessao_id = None
        self.s.status = Sessao.Status.CONCLUIDA
        self.s.codigo_paciente = 'P-AAAAAA'
        self.s.realizada_por = self.f1
        self.s.save()
        self.tentativa(1)
        self.s2 = Sessao.objects.create(fisioterapeuta=self.f1, realizada_por=self.f1, paciente_nome='Maria Silva',
                                        codigo_paciente='P-AAAAAA', status=Sessao.Status.CONCLUIDA)
        self.outra = Sessao.objects.create(fisioterapeuta=self.f1, realizada_por=self.f1, paciente_nome='Joao',
                                           codigo_paciente='P-BBBBBB', status=Sessao.Status.CONCLUIDA)

    def transferir(self, user=None, pk=None, destino=None, escopo='paciente', autora=True):
        return self.prog.transferir_sessoes(user or self.sup, pk or self.s.pk, destino or self.f2.pk, escopo, autora)

    def test_so_o_gestor_transfere(self):
        self.assertEqual(self.transferir(user=self.u1)['erro'], 'sem_permissao')
        self.assertEqual(self.transferir(user=self.u2)['erro'], 'sem_permissao')

    def test_paciente_inteiro_move_so_as_sessoes_dele(self):
        r = self.transferir()
        self.assertEqual(r, {'ok': True, 'transferidas': 2})
        for x in (self.s, self.s2):
            x.refresh_from_db()
            self.assertEqual((x.fisioterapeuta_id, x.realizada_por_id), (self.f2.pk, self.f1.pk))
        self.outra.refresh_from_db()
        self.assertEqual(self.outra.fisioterapeuta_id, self.f1.pk)

    def test_so_uma_sessao(self):
        self.assertEqual(self.transferir(escopo='sessao')['transferidas'], 1)
        self.s2.refresh_from_db()
        self.assertEqual(self.s2.fisioterapeuta_id, self.f1.pk)

    def test_autora_continua_vendo_so_para_consulta(self):
        self.transferir(autora=True)
        self.assertIn(self.s.pk, set(Sessao.objects.visiveis_para(self.u1).values_list('pk', flat=True)))
        self.assertIn(self.s.pk, set(Sessao.objects.visiveis_para(self.u2).values_list('pk', flat=True)))
        # ela abre, mas não altera
        self.assertTrue(self.prog.abrir_sessao(self.u1, self.s.pk)['ok'])
        self.assertEqual(self.prog.salvar_mrc(self.u1, [{'grupo': 'x', 'grau': 1, 'nota': ''}])['erro'], 'sem_permissao')
        self.assertTrue(self.prog.snapshot(self.u1)['sessao']['somente_consulta'])
        self.assertFalse(self.prog.snapshot(self.sup)['sessao'] is None)

    def test_autora_deixa_de_ver_quando_a_supervisora_escolhe(self):
        self.transferir(autora=False)
        self.assertNotIn(self.s.pk, set(Sessao.objects.visiveis_para(self.u1).values_list('pk', flat=True)))
        self.assertEqual(self.prog.abrir_sessao(self.u1, self.s.pk)['erro'], 'nao_encontrado')

    def test_nova_terapeuta_ve_e_edita(self):
        self.transferir()
        self.assertTrue(self.prog.abrir_sessao(self.u2, self.s.pk)['ok'])
        self.assertTrue(self.prog.salvar_mrc(self.u2, [{'grupo': 'Ombro', 'grau': 2, 'nota': ''}])['ok'])
        self.assertFalse(self.prog.snapshot(self.u2)['sessao']['somente_consulta'])
        self.assertEqual(self.prog.snapshot(self.u2)['sessao']['realizada_por'], 'ana')

    def test_historico_mostra_quem_realizou(self):
        self.transferir()
        linhas = {l['id']: l for l in self.prog.listar_historico(self.u2)['sessoes']}
        self.assertEqual(linhas[self.s.pk]['realizada_por'], 'ana')
        self.assertFalse(linhas[self.s.pk]['somente_consulta'])
        da_ana = {l['id']: l for l in self.prog.listar_historico(self.u1)['sessoes']}
        self.assertTrue(da_ana[self.s.pk]['somente_consulta'])

    def test_registro_da_transferencia(self):
        from .models import Transferencia
        self.transferir()
        t = Transferencia.objects.filter(sessao=self.s).get()
        self.assertEqual((t.de_id, t.para_id, t.por_id, t.escopo), (self.f1.pk, self.f2.pk, self.fsup.pk, 'paciente'))

    def test_recusas(self):
        self.assertEqual(self.transferir(destino=self.f1.pk)['erro'], 'mesma_terapeuta')
        self.assertEqual(self.transferir(destino=9999)['erro'], 'destino_invalido')
        self.f2.ativo = False
        self.f2.save()
        self.assertEqual(self.transferir()['erro'], 'destino_invalido')
        self.assertEqual(self.transferir(escopo='tudo')['erro'], 'transferencia_invalida')
        self.assertEqual(self.transferir(pk=9999)['erro'], 'nao_encontrado')
        self.prog.sessao_id = self.s.pk
        self.f2.ativo = True
        self.f2.save()
        self.assertEqual(self.transferir()['erro'], 'sessao_aberta')

    def test_voltar_para_a_autora_devolve_tudo(self):
        self.transferir()
        self.transferir(destino=self.f1.pk)
        self.s.refresh_from_db()
        self.assertEqual((self.s.fisioterapeuta_id, self.s.autora_ve), (self.f1.pk, True))

    def test_codigo_do_paciente_e_reaproveitado_pela_nova_terapeuta(self):
        self.transferir()
        self.assertEqual(self.prog._codigo_do_paciente(self.f2, 'maria  SILVA'), 'P-AAAAAA')
        self.assertNotEqual(self.prog._codigo_do_paciente(self.f2, 'Outro Nome'), 'P-AAAAAA')

    def test_relatorio_mostra_quem_realizou(self):
        from .exportar import dados_relatorio
        self.transferir()
        self.s.refresh_from_db()
        self.assertEqual(dados_relatorio(self.s)['fisio'], 'ana')