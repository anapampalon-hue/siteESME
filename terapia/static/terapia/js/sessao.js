/* sessao.js — desenha a página da sessão a partir do "estado" recebido de dados.js.
   Regras: a tela NÃO calcula nada (resumo vem pronto) e NUNCA usa innerHTML com texto
   vindo de fora (o nome do paciente é digitado pela fisio), só textContent. */

import { T } from './textos.js';
import { iniciar, assinar, enviarComando, obterCurva, simulador, MODO_MOCK } from './dados.js';

const $ = (id) => document.getElementById(id);
const app = $('app');
let estado = null;
let ultimaVersao = -1;      // ignora estados mais antigos que o já exibido
let detalheNumero = null;   // tentativa aberta na janela Detalhe

/* ---------- pequenos ajudantes ---------- */

const hhmm = (iso) => new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
const dataBR = (iso) => iso.split('-').reverse().join('/');

function textoAlcance(a) {
  if (!a || a.cm == null) return T.alcanceNenhum;
  return a.gol ? `${a.cm} cm (gol)` : `${a.cm} cm (bobina ${a.bobina})`;
}

function el(tag, props = {}, ...filhos) {
  const e = document.createElement(tag);
  Object.assign(e, props);
  e.append(...filhos);
  return e;
}

function botao(texto, aoClicar, numeroLinha) {
  const b = el('button', { type: 'button', className: 'botao botao-claro botao-pequeno', textContent: texto, onclick: aoClicar });
  b.dataset.linha = numeroLinha;
  return b;
}

/* ---------- cabeçalho ---------- */

function indicador(elemento, dado, textos) {
  elemento.dataset.estado = dado;
  elemento.querySelector('.ind-texto').textContent = textos[dado];
  elemento.querySelector('.ind-aviso').textContent = dado === 'sem_sinal' ? textos.aviso : '';
}

/* ---------- resumo e lista ---------- */

function renderResumo(r) {
  $('r-validas').textContent = r.tentativas_validas;
  $('r-gols').textContent = r.gols;
  $('r-melhor').textContent = textoAlcance(r.melhor_alcance);
  const caixa = $('r-fluidez');
  caixa.replaceChildren();
  ['alta', 'media', 'baixa', 'indisponivel'].forEach((nivel) => {
    caixa.append(el('span', { className: 'chip' }, el('b', { textContent: r.fluidez[nivel] }), ` ${T.fluidez[nivel]}`));
  });
}

function linha(t) {
  const ativa = t.estado === 'aguardando_disco' || t.estado === 'em_andamento';
  const tr = el('tr', { className: t.anulada ? 'anulada' : ativa ? 'ativa' : '' });
  tr.append(el('th', { scope: 'row', className: 'col-num', textContent: t.numero }));

  if (t.estado === 'aguardando_disco') {
    tr.append(el('td', { colSpan: 4, className: 'col-estado', textContent: T.tentativa.aguardando_disco }));
    return tr;
  }
  if (t.estado === 'em_andamento') {
    tr.append(el('td', { colSpan: 4, className: 'col-estado', textContent: T.tentativa.emAndamento(textoAlcance(t.alcance)) }));
    return tr;
  }

  const tdResultado = el('td', { textContent: t.anulada ? T.resultado.anulada : T.resultado[t.resultado] });
  if (!t.anulada && t.resultado === 'interrompida') {
    tdResultado.append(el('small', { textContent: T.motivoInterrompida[t.motivo] }));
  }

  const tdAlcance = el('td', { textContent: textoAlcance(t.alcance) });

  const tdFluidez = el('td');
  if (!t.anulada) {
    if (t.estado === 'calculando') {
      tdFluidez.textContent = T.tentativa.calculando;
    } else {
      tdFluidez.append(T.fluidez[t.fluidez.nivel]);
      if (t.fluidez.nivel === 'indisponivel') {
        tdFluidez.append(el('small', { textContent: T.motivoFluidez[t.fluidez.motivo] }));
      }
    }
  }

  const tdAcoes = el('td', { className: 'col-acoes' });
  if (t.anulada) {
    tdAcoes.append(botao(T.acoes.restaurar, () => enviarComando('restaurar', { numero: t.numero }), t.numero));
  } else {
    tdAcoes.append(botao(T.acoes.detalhes, () => abrirDetalhe(t.numero), t.numero));
    if (t.estado === 'concluida') {
      tdAcoes.append(botao(T.acoes.anular, () => enviarComando('anular', { numero: t.numero }), t.numero));
    }
  }

  tr.append(tdResultado, tdAlcance, tdFluidez, tdAcoes);
  return tr;
}

function renderLista(tentativas) {
  const corpo = $('lista');
  const linhaComFoco = document.activeElement && document.activeElement.dataset
    ? document.activeElement.dataset.linha : undefined;

  corpo.replaceChildren(...tentativas.map(linha));
  $('tabela').hidden = tentativas.length === 0;
  $('vazio').hidden = tentativas.length > 0;
  $('vazio').textContent = T.semTentativas;

  // a lista é refeita a cada mudança: devolve o foco ao botão da mesma linha (teclado)
  if (linhaComFoco !== undefined) {
    const volta = corpo.querySelector(`button[data-linha="${linhaComFoco}"]`);
    if (volta) volta.focus();
  }
}

/* ---------- tela inteira ---------- */

function renderizar(e) {
  if (e.versao <= ultimaVersao) return;
  ultimaVersao = e.versao;
  estado = e;

  if (e.tela === 'sem_sessao') {
    location.href = app.dataset.urlInicio;
    return;
  }

  const s = e.sessao;
  const espera = e.tela === 'aguardando_mesa';
  const encerrada = e.tela === 'sessao_encerrada';

  // Cabeçalho: completo só com a sessão encerrada; durante a sessão é o reduzido.
  indicador($('ind-mesa'), e.equipamentos.mesa, T.mesa);
  indicador($('ind-batedor'), e.equipamentos.batedor, T.batedor);
  $('nav-completa').hidden = !encerrada;
  $('conta-completa').hidden = !encerrada;
  $('cab-sessao').hidden = encerrada;
  $('cab-paciente').textContent = s.paciente;
  $('cab-inicio-wrap').hidden = !s.inicio;
  if (s.inicio) $('cab-inicio').textContent = hhmm(s.inicio);

  $('tela-espera').hidden = !espera;
  $('tela-sessao').hidden = espera;
  if (espera) return;

  // Topo da sessão encerrada
  $('topo-encerrada').hidden = !encerrada;
  if (encerrada) {
    $('te-paciente').textContent = s.paciente;
    $('te-status').textContent = T.status[s.status];
    $('te-data').textContent = dataBR(s.data);
    $('te-inicio').textContent = hhmm(s.inicio);
    $('te-fim').textContent = hhmm(s.fim);
    $('te-duracao').textContent = `${Math.max(1, Math.round((new Date(s.fim) - new Date(s.inicio)) / 60000))} min`;
  }

  renderResumo(s.resumo);
  renderLista(s.tentativas);

  // Botões de baixo
  const btnEncerrar = $('btn-encerrar');
  btnEncerrar.hidden = encerrada;
  btnEncerrar.disabled = s.encerrando;
  btnEncerrar.textContent = s.encerrando ? T.encerrar.encerrando : T.encerrar.botao;

  $('rodape-encerrada').hidden = !encerrada;
  $('btn-pasta').disabled = !s.pdf;
  $('pdf-caminho').textContent = s.pdf ? T.pdf.salvo(s.pdf) : '';

  if ($('detalhe').open && detalheNumero !== null) preencherDetalhe();
}

/* ---------- janela Detalhe ---------- */

function desenharCurva({ pontos, escala_max }, numero) {
  const NS = 'http://www.w3.org/2000/svg';
  const W = 600, H = 230, ml = 14, mr = 14, mt = 14, mb = 34;
  const tmax = pontos[pontos.length - 1][0] || 1;
  const x = (t) => ml + (t / tmax) * (W - ml - mr);
  const y = (v) => H - mb - (v / escala_max) * (H - mb - mt);   // mesma escala em todas as tentativas

  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', `Curva de velocidade da tentativa ${numero}`);
  const add = (tag, attrs, texto) => {
    const n = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v));
    if (texto != null) n.textContent = texto;
    svg.append(n);
  };

  add('line', { class: 'eixo', x1: ml, y1: y(0), x2: W - mr, y2: y(0) });          // linha do zero
  for (let s = 0; s <= Math.floor(tmax); s++) {
    add('line', { class: 'eixo', x1: x(s), y1: y(0), x2: x(s), y2: y(0) + 5 });
    add('text', { x: x(s), y: y(0) + 19, 'text-anchor': 'middle' }, String(s));
  }
  add('text', { x: W - mr, y: H - 4, 'text-anchor': 'end' }, 'tempo (s)');
  add('text', { x: ml, y: mt + 8 }, 'velocidade');                                  // sem números no eixo vertical
  add('path', {
    class: 'linha',
    d: pontos.map(([t, v], i) => `${i ? 'L' : 'M'}${x(t).toFixed(1)} ${y(v).toFixed(1)}`).join(' '),
  });
  return svg;
}

async function preencherDetalhe() {
  const s = estado.sessao;
  const t = s.tentativas.find((x) => x.numero === detalheNumero);
  if (!t || (t.estado !== 'calculando' && t.estado !== 'concluida')) {
    $('detalhe').close();
    return;
  }

  $('det-titulo').textContent = `Tentativa ${t.numero} · ${s.paciente}`;

  const dRes = $('det-resultado');
  dRes.replaceChildren(t.anulada ? T.resultado.anulada : T.resultado[t.resultado]);
  if (!t.anulada && t.resultado === 'interrompida') dRes.append(el('small', { textContent: T.motivoInterrompida[t.motivo] }));

  $('det-alcance').textContent = textoAlcance(t.alcance);

  const dFlu = $('det-fluidez');
  dFlu.replaceChildren();
  if (t.estado === 'calculando') {
    dFlu.append(T.tentativa.calculando);
  } else {
    dFlu.append(T.fluidez[t.fluidez.nivel]);
    if (t.fluidez.nivel === 'indisponivel') dFlu.append(el('small', { textContent: T.motivoFluidez[t.fluidez.motivo] }));
  }

  const area = $('det-curva');
  const legenda = $('det-legenda');
  if (t.estado === 'calculando') {
    area.replaceChildren(el('p', { className: 'det-vazio', textContent: T.detalhe.calculando }));
    legenda.textContent = '';
  } else if (t.fluidez.nivel === 'indisponivel') {
    area.replaceChildren(el('p', { className: 'det-vazio', textContent: T.detalhe.semCurva[t.fluidez.motivo] }));
    legenda.textContent = '';
  } else {
    const curva = await obterCurva(t.numero);
    if (detalheNumero !== t.numero) return;   // o usuário já trocou de tentativa
    area.replaceChildren(curva ? desenharCurva(curva, t.numero) : el('p', { className: 'det-vazio', textContent: T.detalhe.semCurva.sem_dados_batedor }));
    legenda.textContent = curva ? T.detalhe.legenda : '';
  }

  const numeros = s.tentativas
    .filter((x) => x.estado === 'calculando' || x.estado === 'concluida')
    .map((x) => x.numero)
    .sort((a, b) => a - b);
  const i = numeros.indexOf(t.numero);
  $('det-anterior').disabled = i <= 0;
  $('det-proxima').disabled = i >= numeros.length - 1;
  $('det-anular').textContent = t.anulada ? T.acoes.restaurar : T.acoes.anular;
  $('det-anular').disabled = t.estado !== 'concluida';
}

function irParaVizinha(passo) {
  const numeros = estado.sessao.tentativas
    .filter((x) => x.estado === 'calculando' || x.estado === 'concluida')
    .map((x) => x.numero)
    .sort((a, b) => a - b);
  const novo = numeros[numeros.indexOf(detalheNumero) + passo];
  if (novo !== undefined) { detalheNumero = novo; preencherDetalhe(); }
}

function abrirDetalhe(numero) {
  detalheNumero = numero;
  preencherDetalhe();
  if (!$('detalhe').open) $('detalhe').showModal();
}

/* ---------- eventos da página ---------- */

function ligarEventos() {
  $('btn-cancelar-espera').addEventListener('click', () => enviarComando('cancelar_espera'));

  // Encerrar com confirmação
  $('btn-encerrar').addEventListener('click', () => {
    const semTentativas = estado.sessao.tentativas.filter((t) => t.estado !== 'aguardando_disco').length === 0;
    $('confirmar-texto').textContent = semTentativas ? T.encerrar.semTentativas : T.encerrar.pergunta(estado.sessao.paciente);
    $('confirmar').returnValue = '';
    $('confirmar').showModal();
  });
  $('confirmar').addEventListener('close', () => {
    if ($('confirmar').returnValue === 'sim') enviarComando('encerrar_sessao');
  });

  $('btn-pdf').addEventListener('click', () => enviarComando('gerar_pdf'));
  $('btn-pasta').addEventListener('click', () => enviarComando('abrir_pasta'));

  // Janela Detalhe
  $('det-fechar').addEventListener('click', () => $('detalhe').close());
  $('detalhe').addEventListener('close', () => { detalheNumero = null; });
  $('det-anterior').addEventListener('click', () => irParaVizinha(-1));
  $('det-proxima').addEventListener('click', () => irParaVizinha(1));
  $('det-anular').addEventListener('click', () => {
    const t = estado.sessao.tentativas.find((x) => x.numero === detalheNumero);
    if (t) enviarComando(t.anulada ? 'restaurar' : 'anular', { numero: t.numero });
  });
  $('detalhe').addEventListener('keydown', (ev) => {
    if (ev.key === 'ArrowLeft') irParaVizinha(-1);
    if (ev.key === 'ArrowRight') irParaVizinha(1);
  });

  // Painel de demonstração (só enquanto o back for de mentira)
  if (MODO_MOCK) {
    $('demo').hidden = false;
    $('demo').addEventListener('click', (ev) => {
      const b = ev.target.closest('button[data-acao]');
      if (b && simulador[b.dataset.acao]) simulador[b.dataset.acao]();
    });
  }
}

/* ---------- partida ---------- */

const params = new URLSearchParams(location.search);
iniciar({ conta: app.dataset.conta, cenario: params.get('cenario') });
ligarEventos();
assinar(renderizar);