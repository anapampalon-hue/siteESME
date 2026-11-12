"""
exportar.py — monta o que sai do programa: o RELATÓRIO da sessão (página para "Salvar como PDF") e o CSV.

SESSÃO ANÔNIMA (sem o "check" do TCLE): sem código, sem data, sem horário e sem nome; só os dados das tentativas.

PSEUDONIMIZAÇÃO: por padrão nada aqui leva o nome do paciente, só o código (campos.codigo_paciente).
  * Relatório: o nome só entra se o terapeuta marcar "Incluir o nome do paciente" (?nome=1).
  * CSV: nunca leva nome nem comentário (o comentário é texto livre e pode citar dados do paciente);
    serve para planilhas e análises. Tentativas anuladas vão marcadas (anulada = sim); no relatório elas ficam de fora.
  * A avaliação do terapeuta (qualidade do movimento e dor) vai no CSV só como números; as ANOTAÇÕES (texto livre), o MRC
    e as escalas aplicadas (Fugl-Meyer, Wolf Motor) ficam só no relatório.
"""
import csv
import io

from . import evolucao
from .estado import _alcance, _avaliavel, _duracao_min, _feedback_de, _resumo
from .models import Feedback

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
    ml, mr, mt, mb = 30, 10, 26, 34
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
            f'<rect x="{ml + 8}" y="9" width="36" height="8" class="area"/><line x1="{ml + 8}" y1="9" x2="{ml + 44}" y2="9" class="linha"/>'
            f'<text x="{ml + 52}" y="17">Velocidade do batedor ao longo da tentativa</text>'
            f'{ticks}<text x="{(ml + largura - mr) / 2:.1f}" y="{altura - 4}" text-anchor="middle">tempo (s)</text>'
            f'<text x="11" y="{(mt + base) / 2:.1f}" text-anchor="middle" transform="rotate(-90 11 {(mt + base) / 2:.1f})">velocidade</text></svg>')


def _evolucao_svg(series, largura=640, altura=190):
    """Curvas em tempo normalizado (0 a 100 %). series: [{'y': [100 valores], 'classe': css, 'rotulo': texto, 'faixa': [dp]?}].
    A legenda vai dentro do desenho (no PDF não há caixinhas para ligar e desligar)."""
    series = [x for x in series if x and x.get('y')]
    if not series:
        return ''
    tem_faixa = any(x.get('faixa') for x in series)
    nleg = len(series) + (1 if tem_faixa else 0)
    ml, mr, mt, mb = 30, 10, 8 + 16 * nleg, 34
    vmax = max(v + (x['faixa'][i] if x.get('faixa') else 0) for x in series for i, v in enumerate(x['y'])) * 1.05 or 1
    x_ = lambda i: ml + i / 99 * (largura - ml - mr)
    y_ = lambda v: altura - mb - v / vmax * (altura - mb - mt)
    out = []
    for sr in series:
        if sr.get('faixa'):
            cima = ' '.join(f"{'L' if i else 'M'}{x_(i):.1f} {y_(v + sr['faixa'][i]):.1f}" for i, v in enumerate(sr['y']))
            baixo = ' '.join(f"L{x_(99 - i):.1f} {y_(max(0, sr['y'][99 - i] - sr['faixa'][99 - i])):.1f}" for i in range(100))
            out.append(f'<path d="{cima} {baixo} Z" class="evo-faixa"/>')
    for sr in series:
        out.append(f'<path d="' + ' '.join(f"{'L' if i else 'M'}{x_(i):.1f} {y_(v):.1f}" for i, v in enumerate(sr['y']))
                   + f'" class="{sr["classe"]}"/>')
    base = y_(0)
    out.append(f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{base:.1f}" class="eixo"/>'
               f'<line x1="{ml}" y1="{base:.1f}" x2="{largura - mr}" y2="{base:.1f}" class="eixo"/>')
    for p in (0, 20, 40, 60, 80, 100):
        xi = ml + p / 100 * (largura - ml - mr)
        out.append(f'<line x1="{xi:.1f}" y1="{base:.1f}" x2="{xi:.1f}" y2="{base + 4:.1f}" class="eixo"/>'
                   f'<text x="{xi:.1f}" y="{base + 16:.1f}" text-anchor="middle">{p}</text>')
    for k, sr in enumerate(series):                  # legenda no alto
        yy = 12 + 16 * k
        out.append(f'<line x1="{ml + 8}" y1="{yy - 4}" x2="{ml + 44}" y2="{yy - 4}" class="{sr["classe"]}"/>'
                   f'<text x="{ml + 52}" y="{yy}">{sr["rotulo"]}</text>')
    if tem_faixa:
        yy = 12 + 16 * len(series)
        out.append(f'<rect x="{ml + 8}" y="{yy - 9}" width="36" height="10" class="evo-faixa"/>'
                   f'<text x="{ml + 52}" y="{yy}">Faixa clara: variação entre as tentativas (desvio padrão)</text>')
    out.append(f'<text x="{(ml + largura - mr) / 2:.1f}" y="{altura - 4}" text-anchor="middle">tempo da tentativa (%)</text>'
               f'<text x="11" y="{(mt + base) / 2:.1f}" text-anchor="middle" transform="rotate(-90 11 {(mt + base) / 2:.1f})">velocidade</text>')
    return f'<svg viewBox="0 0 {largura} {altura}" role="img" aria-label="Velocidade em função do tempo normalizado">{"".join(out)}</svg>'


def _avaliacao(t):
    """Avaliação do terapeuta já em texto. Tentativa que não entra na avaliação (interrompida) não leva nada."""
    if not _avaliavel(t):
        return {'avaliavel': False, 'estrelas': '', 'qualidade': None, 'dor': '', 'dor_num': None, 'nota': ''}
    f = _feedback_de(t)
    q = f.qualidade if f else None
    d = f.dor if f else None
    return {
        'avaliavel': True, 'qualidade': q,
        'estrelas': ('★' * (q or 0)) + ('☆' * (5 - (q or 0))),     # sem nota: as 5 estrelas vazias
        'dor': f'{d} · {Feedback.DOR_TEXTO[d]}' if d is not None else 'não informada', 'dor_num': d,
        'nota': (f.nota if f else '') or '',
    }


def _fluidez(t):
    nivel = t.fluidez_nivel or 'indisponivel'
    motivo = (t.fluidez_motivo or 'nao_calculada') if nivel == 'indisponivel' else ''
    return nivel, motivo


def dados_relatorio(sessao, com_nome=False):
    """Tudo que o modelo do relatório precisa, já em texto."""
    tents = list(sessao.tentativas.select_related('feedback').order_by('numero'))
    finais = [t for t in tents if t.finalizada_em is not None]
    validas = [t for t in finais if not t.anulada]
    resumo = _resumo(finais)
    escala = max((t.curva['v_max'] for t in validas if t.curva), default=0)

    anonima = sessao.anonima
    ev = None if anonima else evolucao.evolucao_da_sessao(sessao)
    antes = ev['antes'] if ev else None
    rot_antes = f"Média das sessões anteriores ({antes['n']} tent.), tracejada azul" if antes else ''

    linhas = []
    for t in validas:                                # anuladas ficam de fora do relatório
        nivel, motivo = _fluidez(t)
        linhas.append({
            'numero': t.numero, 'resultado': TEXTO_RESULTADO.get(t.resultado, t.resultado),
            'motivo': TEXTO_MOTIVO.get(t.motivo, ''), 'alcance': texto_alcance(_alcance(t)),
            'fluidez': TEXTO_FLUIDEZ[nivel], 'fluidez_motivo': TEXTO_FLUIDEZ_MOTIVO.get(motivo, ''),
            'curva_svg': _curva_svg(t.curva['pontos'], escala) if t.curva else '',
            'evo_svg': _evolucao_svg([
                {'y': antes['y'], 'faixa': antes['dp'], 'classe': 'evo-antes', 'rotulo': rot_antes},
                {'y': evolucao.normalizar(t.curva), 'classe': 'evo-esta', 'rotulo': f'Tentativa {t.numero}'},
            ]) if (antes and t.curva) else '',
            'aval': _avaliacao(t),
        })
    mrc = [{'grupo': m.grupo, 'grau': m.grau, 'nota': m.nota or ''} for m in sessao.mrc.all()
           if m.grupo.strip() or m.grau is not None or (m.nota or '').strip()]
    return {
        'anonima': anonima,
        'codigo': sessao.garantir_codigo(),
        'nome': sessao.paciente_nome if com_nome and not anonima else None,
        'fisio': (sessao.realizada_por or sessao.fisioterapeuta).nome,     # quem conduziu a sessão (não muda na transferência)
        # sessão anônima: sem data e sem horário (a tela mostra 00/00/0000)
        'data': None if anonima else sessao.data_sessao,
        'inicio': None if anonima else sessao.iniciada_em, 'fim': None if anonima else sessao.finalizada_em,
        'duracao_min': _duracao_min(sessao),
        'status': 'Interrompida' if sessao.status == 'em_andamento' else 'Concluída',
        'validas': resumo['tentativas_validas'], 'gols': resumo['gols'],
        'melhor': texto_alcance(resumo['melhor_alcance']),
        'fluidez_total': [(TEXTO_FLUIDEZ[k], resumo['fluidez'][k]) for k in ('alta', 'media', 'baixa', 'indisponivel')],
        'comentario': sessao.comentario or '',
        'tentativas': linhas,
        'mrc': mrc,
        'escalas': _escalas(sessao),
        'evolucao_svg': _evolucao_svg([
            {'y': antes['y'], 'classe': 'evo-antes', 'rotulo': f"Antes da sessão ({antes['n']} tent., {ev['sessoes_antes']} sess.)"} if antes else None,
            {'y': ev['esta']['y'], 'classe': 'evo-esta', 'rotulo': f"Esta sessão ({ev['esta']['n']} tent.)"} if ev and ev['esta'] else None,
            {'y': ev['atualizada']['y'], 'classe': 'evo-atual', 'rotulo': f"Evolução atualizada ({ev['atualizada']['n']} tent.)"} if antes and ev['atualizada'] else None,
        ]) if (ev and antes) else '',
    }


def _escalas(sessao):
    """Escalas aplicadas pelo terapeuta: só as preenchidas, uma tabela por escala. Vazio = nada no relatório.
    Cada item: {'titulo', 'nota', 'linhas': [(medida, resultado), ...]}."""
    virgula = lambda v: str(v).replace('.', ',')
    itens = []
    if sessao.fma_total is not None:
        itens.append({'titulo': 'Fugl-Meyer (membro superior)',
                      'nota': 'Avalia a função motora do membro superior, de 0 a 66 pontos. Aplicado pelo terapeuta.',
                      'linhas': [('Pontuação total', f'{sessao.fma_total} de 66')]})
    if sessao.wmft_tempo is not None and sessao.wmft_nota is not None:
        itens.append({'titulo': 'Wolf Motor Function Test (WMFT)',
                      'nota': 'Mede o tempo e a qualidade de tarefas funcionais com o membro afetado. Aplicado pelo terapeuta.',
                      'linhas': [('Tempo médio por tarefa', f'{virgula(sessao.wmft_tempo)} s'),
                                 ('Nota média', f'{virgula(sessao.wmft_nota)} de 5')]})
    return itens


def gerar_csv(sessao):
    """CSV com ; e BOM (abre direto no Excel em português). Sem nome do paciente, sem comentário e sem anotações."""
    saida = io.StringIO()
    w = csv.writer(saida, delimiter=';', lineterminator='\r\n')
    w.writerow(['codigo_paciente', 'data_sessao', 'inicio', 'fim', 'tentativa', 'resultado', 'motivo', 'alcance_cm',
                'bobina', 'gol', 'fluidez', 'fluidez_motivo', 'anulada', 'velocidade_pico_m_s', 'qualidade_movimento', 'dor'])
    anonima = sessao.anonima                          # sem código, sem data e sem horário
    ini = sessao.iniciada_em.isoformat(timespec='minutes') if sessao.iniciada_em and not anonima else ''
    fim = sessao.finalizada_em.isoformat(timespec='minutes') if sessao.finalizada_em and not anonima else ''
    codigo = 'anonimo' if anonima else sessao.garantir_codigo()
    data = '' if anonima else sessao.data_sessao.isoformat()
    for t in sessao.tentativas.select_related('feedback').filter(finalizada_em__isnull=False).order_by('numero'):
        a = _alcance(t)
        nivel, motivo = _fluidez(t)
        av = _avaliacao(t)
        w.writerow([codigo, data, ini, fim, t.numero, t.resultado, t.motivo,
                    a['cm'] if a['cm'] is not None else '', a['bobina'] or '', 'sim' if a['gol'] else 'não',
                    nivel, motivo, 'sim' if t.anulada else 'não',
                    str(t.curva['v_max']).replace('.', ',') if t.curva else '',
                    av['qualidade'] if av['qualidade'] is not None else '', av['dor_num'] if av['dor_num'] is not None else ''])
    return '﻿' + saida.getvalue()