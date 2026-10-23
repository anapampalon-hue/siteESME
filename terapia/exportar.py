"""
exportar.py — monta o que sai do programa: o RELATÓRIO da sessão (página para "Salvar como PDF") e o CSV.

PSEUDONIMIZAÇÃO: por padrão nada aqui leva o nome do paciente, só o código (campos.codigo_paciente).
  * Relatório: o nome só entra se a terapeuta marcar "Incluir o nome do paciente" (?nome=1).
  * CSV: nunca leva nome nem comentário (o comentário é texto livre e pode citar dados do paciente);
    serve para planilhas e análises. Tentativas anuladas vão marcadas (anulada = sim); no relatório elas ficam de fora.
"""
import csv
import io

from .estado import _alcance, _duracao_min, _resumo

TEXTO_RESULTADO = {'gol': 'Gol', 'parou': 'Parou', 'interrompida': 'Interrompida'}
TEXTO_MOTIVO = {
    'nova_tentativa': 'nova tentativa apertada antes do fim',
    'nova_sessao': 'a mesa foi zerada durante a tentativa',
    'mesa_reiniciou': 'a mesa reiniciou durante a tentativa',
}
TEXTO_FLUIDEZ = {'alta': 'alta', 'media': 'média', 'baixa': 'baixa', 'indisponivel': 'indisponível'}
TEXTO_FLUIDEZ_MOTIVO = {
    'sem_dados_batedor': 'sem dados do batedor',
    'sem_repouso': 'sem repouso de referência',
    'nao_calculada': 'cálculo não concluído',
}


def texto_alcance(a):
    if a['cm'] is None:
        return 'nenhum'
    return f"{a['cm']} cm (gol)" if a['gol'] else f"{a['cm']} cm (bobina {a['bobina']})"


def _curva_svg(pontos, escala_max, largura=640, altura=170):
    """Curva de velocidade como SVG simples (mesma escala em todas as fichas; sem números no eixo vertical)."""
    if not pontos or not escala_max:
        return ''
    ml, mr, mt, mb = 16, 10, 8, 34
    tmax = pontos[-1][0] or 1
    x = lambda t: ml + t / tmax * (largura - ml - mr)
    y = lambda v: altura - mb - v / escala_max * (altura - mb - mt)
    topo = ' '.join(f"{'L' if i else 'M'}{x(t):.1f} {y(v):.1f}" for i, (t, v) in enumerate(pontos))
    base = y(0)
    ticks = ''
    passo = 0.5 if tmax > 1.2 else 0.2
    s = 0.0
    while s <= tmax + 1e-9:
        ticks += (f'<line x1="{x(s):.1f}" y1="{base:.1f}" x2="{x(s):.1f}" y2="{base + 4:.1f}" class="eixo"/>'
                  f'<text x="{x(s):.1f}" y="{base + 16:.1f}" text-anchor="middle">{str(round(s, 1)).replace(".", ",")}</text>')
        s += passo
    return (f'<svg viewBox="0 0 {largura} {altura}" role="img" aria-label="Curva de velocidade da tentativa">'
            f'<path d="{topo} L{x(tmax):.1f} {base:.1f} L{x(0):.1f} {base:.1f} Z" class="area"/>'
            f'<path d="{topo}" class="linha"/>'
            f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{base:.1f}" class="eixo"/>'
            f'<line x1="{ml}" y1="{base:.1f}" x2="{largura - mr}" y2="{base:.1f}" class="eixo"/>'
            f'{ticks}<text x="{(ml + largura - mr) / 2:.1f}" y="{altura - 4}" text-anchor="middle">tempo (s)</text></svg>')


def _fluidez(t):
    nivel = t.fluidez_nivel or 'indisponivel'
    motivo = (t.fluidez_motivo or 'nao_calculada') if nivel == 'indisponivel' else ''
    return nivel, motivo


def dados_relatorio(sessao, com_nome=False):
    """Tudo que o modelo do relatório precisa, já em texto."""
    tents = list(sessao.tentativas.order_by('numero'))
    finais = [t for t in tents if t.finalizada_em is not None]
    validas = [t for t in finais if not t.anulada]
    resumo = _resumo(finais)
    escala = max((t.curva['v_max'] for t in validas if t.curva), default=0)

    linhas = []
    for t in validas:                                # anuladas ficam de fora do relatório
        nivel, motivo = _fluidez(t)
        linhas.append({
            'numero': t.numero, 'resultado': TEXTO_RESULTADO.get(t.resultado, t.resultado),
            'motivo': TEXTO_MOTIVO.get(t.motivo, ''), 'alcance': texto_alcance(_alcance(t)),
            'fluidez': TEXTO_FLUIDEZ[nivel], 'fluidez_motivo': TEXTO_FLUIDEZ_MOTIVO.get(motivo, ''),
            'curva_svg': _curva_svg(t.curva['pontos'], escala) if t.curva else '',
        })
    return {
        'codigo': sessao.garantir_codigo(),
        'nome': sessao.paciente_nome if com_nome else None,
        'fisio': sessao.fisioterapeuta.nome,
        'data': sessao.data_sessao, 'inicio': sessao.iniciada_em, 'fim': sessao.finalizada_em,
        'duracao_min': _duracao_min(sessao),
        'status': 'Interrompida' if sessao.status == 'em_andamento' else 'Concluída',
        'validas': resumo['tentativas_validas'], 'gols': resumo['gols'],
        'melhor': texto_alcance(resumo['melhor_alcance']),
        'fluidez_total': [(TEXTO_FLUIDEZ[k], resumo['fluidez'][k]) for k in ('alta', 'media', 'baixa', 'indisponivel')],
        'comentario': sessao.comentario or '',
        'tentativas': linhas,
    }


def gerar_csv(sessao):
    """CSV com ; e BOM (abre direto no Excel em português). Sem nome do paciente e sem comentário."""
    saida = io.StringIO()
    w = csv.writer(saida, delimiter=';', lineterminator='\r\n')
    w.writerow(['codigo_paciente', 'data_sessao', 'inicio', 'fim', 'tentativa', 'resultado', 'motivo', 'alcance_cm',
                'bobina', 'gol', 'fluidez', 'fluidez_motivo', 'anulada', 'velocidade_pico_m_s'])
    ini = sessao.iniciada_em.isoformat(timespec='minutes') if sessao.iniciada_em else ''
    fim = sessao.finalizada_em.isoformat(timespec='minutes') if sessao.finalizada_em else ''
    for t in sessao.tentativas.filter(finalizada_em__isnull=False).order_by('numero'):
        a = _alcance(t)
        nivel, motivo = _fluidez(t)
        w.writerow([sessao.garantir_codigo(), sessao.data_sessao.isoformat(), ini, fim, t.numero, t.resultado, t.motivo,
                    a['cm'] if a['cm'] is not None else '', a['bobina'] or '', 'sim' if a['gol'] else 'não',
                    nivel, motivo, 'sim' if t.anulada else 'não',
                    str(t.curva['v_max']).replace('.', ',') if t.curva else ''])
    return '﻿' + saida.getvalue()