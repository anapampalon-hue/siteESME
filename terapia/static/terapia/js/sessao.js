/* sessao.js — desenha a página da Sessão a partir do "estado" recebido de dados.js.
   Regras: a tela NÃO calcula nada e NUNCA usa innerHTML com texto vindo de fora
   (o nome do paciente é digitado pela fisio): só textContent. */

import { T } from './textos.js?v=4';
import * as dados from './dados.js?v=4';

const { iniciar, assinar, enviarComando, obterCurva } = dados;

const $ = (id) => document.getElementById(id);
const app = $('app');
let estado = null;
let ultimaVersao = -1;       // ignora estados mais antigos que o já exibido
let detalheNumero = null;    // tentativa aberta na janela Detalhe
let detalheChave = null;     // o que a janela Detalhe está mostrando (evita redesenhar à toa)
const COMENTARIO_MAX = 2000;
let comTimer = null;         // espera ~0,8 s depois da última letra para salvar
let comSalvando = false;
let comIdSessao = null;      // comentário pertence a esta sessão (se mudar de sessão, recarrega o texto)

/* ---------- pequenos ajudantes ---------- */

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
  const b = el('button', { type: 'button', className: 'botao botao-claro ses-btn', textContent: texto, onclick: aoClicar });
  b.dataset.linha = numeroLinha;
  return b;
}

function pontinhos() {
  const p = el('span', { className: 'ses-pontinhos' }, el('i'), el('i'), el('i'));
  p.setAttribute('aria-hidden', 'true');
  return p;
}

const dataBR = (iso) => (iso ? iso.split('-').reverse().join('/') : '');                  // 2026-10-22 -> 22/10/2026
const horaBR = (iso) => (iso ? new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '');

/* ---------- topo: mesa e batedor ---------- */

function indicador(elemento, dado, textos) {
  elemento.dataset.estado = dado;                       // o CSS pinta: ok = verde, sem_sinal = vermelha
  elemento.querySelector('.ind-texto').textContent = textos[dado];
}

/* ---------- cartão "O que fazer agora" ---------- */

function renderGuia(e) {
  const s = e.sessao;
  const ultima = s.tentativas[0];                 // a mais recente
  let frase = T.guia.pronto;
  if (e.tela === 'sessao_encerrada') frase = s.status === 'interrompida' ? T.guia.interrompida : T.guia.encerrada;
  else if (s.encerrando || (ultima && ultima.estado === 'em_andamento')) frase = T.guia.discoRolando;
  else if (ultima && ultima.estado === 'aguardando_disco') frase = T.guia.aguardandoDisco;

  const f = $('guia-frase');
  if (f.textContent !== frase) {                  // só mexe (e anima) quando a frase muda
    f.textContent = frase;
    f.classList.remove('troca');
    void f.offsetWidth;
    f.classList.add('troca');
  }

  // aviso de sem sinal: uma linha de altura reservada, então nada na página se mexe
  const semMesa = e.equipamentos.mesa === 'sem_sinal';
  const semBatedor = e.equipamentos.batedor === 'sem_sinal';
  const leitura = e.tela === 'sessao_encerrada';          // sessão já terminada: sinal das placas não importa mais
  $('guia-aviso').textContent = leitura ? '' : semMesa && semBatedor ? T.guia.avisoAmbos : semMesa ? T.guia.avisoMesa : semBatedor ? T.guia.avisoBatedor : '';
}

/* ---------- totais ---------- */

function caixaFluidez(nivel, quantidade, rotulo) {
  return el('li', { className: `ses-caixa ses-caixa-${nivel}` }, el('strong', { textContent: quantidade }), el('span', { textContent: rotulo }));
}

function renderResumo(r) {
  $('res-validas').textContent = r.tentativas_validas;
  $('res-gols').textContent = r.gols;
  $('res-melhor').textContent = textoAlcance(r.melhor_alcance);
  const caixas = ['alta', 'media', 'baixa', 'indisponivel'].map((k) => caixaFluidez(k, r.fluidez[k], T.fluidez[k]));
  if (r.fluidez.calculando) caixas.push(caixaFluidez('calculando', r.fluidez.calculando, T.resumo.calculando));
  $('res-fluidez').replaceChildren(...caixas);
}

/* ---------- tabela ---------- */

function celulaFluidez(t) {
  const td = el('td');
  if (t.estado === 'calculando') {
    td.append(el('span', { className: 'ses-calculando' }, pontinhos(), T.tentativa.calculando));
  } else {
    td.append(T.fluidez[t.fluidez.nivel]);
    if (t.fluidez.nivel === 'indisponivel') td.append(el('small', { textContent: T.motivoFluidez[t.fluidez.motivo] }));
  }
  return td;
}

function linha(t) {
  const emCurso = t.estado === 'aguardando_disco' || t.estado === 'em_andamento';
  const tr = el('tr', { className: t.anulada ? 'ses-anulada' : emCurso ? 'ses-ativa' : '' });

  const tdNum = el('th', { scope: 'row', className: 'ses-num', textContent: t.numero });
  if (t.anulada) tdNum.append(el('span', { className: 'ses-rotulo-anulada', textContent: T.anulada }));
  tr.append(tdNum);

  if (t.estado === 'aguardando_disco') {
    tr.append(el('td', { colSpan: 4, className: 'ses-estado', textContent: T.tentativa.aguardando_disco }));
    return tr;
  }
  if (t.estado === 'em_andamento') {
    tr.append(el('td', { colSpan: 4, className: 'ses-estado', textContent: T.tentativa.emAndamento(textoAlcance(t.alcance)) }));
    return tr;
  }

  const tdResultado = el('td', { textContent: T.resultado[t.resultado] });
  if (t.motivo) tdResultado.append(el('small', { textContent: T.motivoTentativa[t.motivo] }));

  const tdAcoes = el('td', { className: 'ses-acoes' });
  if (t.anulada) {
    tdAcoes.append(botao(T.acoes.restaurar, () => enviarComando('restaurar', { numero: t.numero }), t.numero));
  } else {
    tdAcoes.append(botao(T.acoes.detalhes, () => abrirDetalhe(t.numero), t.numero));
    tdAcoes.append(botao(T.acoes.anular, () => enviarComando('anular', { numero: t.numero }), t.numero));
  }

  tr.append(tdResultado, el('td', { textContent: textoAlcance(t.alcance) }), celulaFluidez(t), tdAcoes);
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

/* ---------- comentário da terapeuta (opcional) ---------- */

function atualizarContador() {
  const n = $('com-texto').value.length;
  $('com-contador').textContent = T.comentario.contador(n, COMENTARIO_MAX);
}

function estadoComentario(texto) {
  $('com-estado').textContent = texto;
}

function renderComentario(s) {
  const ta = $('com-texto');
  const noPrograma = s.comentario || '';
  $('com-dica').textContent = T.comentario.dica;
  ta.placeholder = T.comentario.placeholder;
  const trocouDeSessao = comIdSessao !== s.id;
  comIdSessao = s.id;
  // nunca sobrescreve o que ela está digitando: só atualiza se o campo está parado
  const digitando = document.activeElement === ta || comTimer !== null || comSalvando;
  if ((trocouDeSessao || !digitando) && ta.value !== noPrograma) ta.value = noPrograma;
  atualizarContador();
}

async function salvarComentario() {
  clearTimeout(comTimer);
  comTimer = null;
  if (comSalvando) { comTimer = setTimeout(salvarComentario, 300); return; }   // espera o envio anterior terminar
  comSalvando = true;
  estadoComentario(T.comentario.salvando);
  $('com-erro').hidden = true;
  const r = await enviarComando('salvar_comentario', { texto: $('com-texto').value });
  comSalvando = false;
  if (r.ok) {
    estadoComentario(comTimer ? T.comentario.salvando : T.comentario.salvo);
  } else {
    estadoComentario('');
    $('com-erro').hidden = false;
    $('com-erro').textContent = T.erros[r.erro] || T.erroGenerico(r.erro);
  }
}

/** Salva já o que estiver pendente (antes de exportar, fechar ou sair da página). */
async function salvarPendente() {
  while (comTimer !== null || comSalvando) {
    if (comTimer !== null && !comSalvando) await salvarComentario();
    else await new Promise((r) => setTimeout(r, 50));
  }
}

/* ---------- rodapé: encerrar, fechar, exportar ---------- */

const urlDe = (modelo, id) => modelo.replace('/0/', `/${id}/`).replace(/\/0$/, `/${id}`);
const veioDoHistorico = new URLSearchParams(location.search).get('de') === 'historico';

function renderRodape(e) {
  const s = e.sessao;
  const encerrada = e.tela === 'sessao_encerrada';
  const interrompida = s.status === 'interrompida';
  const b = $('b-encerrar');
  $('fluidez-final').hidden = !encerrada;         // as caixinhas de fluidez só aparecem com a sessão encerrada
  b.textContent = encerrada ? T.sessao.fechar : s.encerrando ? T.sessao.encerrando : T.sessao.encerrar;
  b.disabled = !!s.encerrando;

  // sessão que ficou aberta (programa fechado no meio): aviso + botão "Encerrar sessão"
  $('aviso-interrompida').hidden = !interrompida;
  $('aviso-interrompida').textContent = interrompida ? T.sessao.interrompida : '';
  $('b-concluir').hidden = !interrompida;

  // sessão anônima: lembra que ela não fica salva (e avisa antes de "Fechar" apagar tudo)
  $('aviso-anonima').hidden = !s.anonima;
  $('aviso-anonima').textContent = s.anonima ? (encerrada ? T.sessao.anonimaFechar : T.sessao.anonima) : '';

  // exportar: depois que a sessão terminou (ou foi aberta do histórico)
  $('exportar').hidden = !encerrada;
  if (encerrada) {
    $('b-pdf').href = urlDe(app.dataset.urlRelatorio, s.id);
    $('b-csv').href = urlDe(app.dataset.urlCsv, s.id);
    $('b-pdf').textContent = T.exportar.pdf;
    $('b-csv').textContent = T.exportar.csv;
  }
}

/* ---------- página inteira ---------- */

function mostrarErro(texto) {
  $('faixa-erro').hidden = false;
  $('faixa-erro').textContent = texto;
}

function renderizar(e) {
  try {
    desenhar(e);
  } catch (erro) {                       // se algo der errado, a tela mostra o motivo em vez de ficar parada
    console.error('ESME: erro ao desenhar a Sessão —', erro);
    mostrarErro(`Erro na tela: ${erro.message}`);
  }
}

function desenhar(e) {
  $('faixa-erro').hidden = !e.semConexao;
  $('faixa-erro').textContent = e.semConexao ? T.semConexao : '';
  if (e.versao <= ultimaVersao && !e.semConexao) return;
  ultimaVersao = e.versao;
  estado = e;

  if (e.tela === 'sem_sessao') { location.href = veioDoHistorico ? app.dataset.urlHistorico : app.dataset.urlInicio; return; }     // abriu /sessao/ sem sessão
  if (e.tela === 'aguardando_mesa') { location.href = app.dataset.urlEspera; return; }

  const s = e.sessao;
  const anonima = !!s.anonima;                       // sem o TCLE: "Anônimo", sem código, sem data real e sem horário
  $('cab-paciente').textContent = s.paciente;
  $('cab-codigo').textContent = s.codigo;
  $('cab-codigo-wrap').hidden = anonima;
  $('cab-data').textContent = anonima ? T.novaSessao.dataAnonima : dataBR(s.data);
  $('cab-hora-wrap').hidden = anonima;
  $('cab-inicio').textContent = horaBR(s.inicio);
  $('cab-fim-wrap').hidden = anonima || !s.fim;
  $('cab-fim').textContent = horaBR(s.fim);
  indicador($('ind-mesa'), e.equipamentos.mesa, T.mesa);
  indicador($('ind-batedor'), e.equipamentos.batedor, T.batedor);
  renderResumo(s.resumo);
  renderGuia(e);
  renderLista(s.tentativas);
  renderComentario(s);
  renderRodape(e);

  if ($('detalhe').open && detalheNumero !== null) preencherDetalhe();
}

/* ---------- janela Detalhe ---------- */

const numeroBR = (n) => n.toLocaleString('pt-BR');   // 0,5  1  1,5

function desenharCurva({ pontos, escala_max }, numero) {
  const NS = 'http://www.w3.org/2000/svg';
  const W = 640, H = 250, ml = 40, mr = 16, mt = 14, mb = 44;
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

  const topo = pontos.map(([t, v], i) => `${i ? 'L' : 'M'}${x(t).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
  add('path', { class: 'area', d: `${topo} L${x(tmax).toFixed(1)} ${y(0)} L${x(0)} ${y(0)} Z` });
  add('path', { class: 'linha', d: topo });

  add('line', { class: 'eixo', x1: ml, y1: mt, x2: ml, y2: y(0) });                  // eixo vertical (sem números)
  add('line', { class: 'eixo', x1: ml, y1: y(0), x2: W - mr, y2: y(0) });            // eixo do tempo
  const passo = tmax > 3 ? 1 : tmax > 1.2 ? 0.5 : 0.2;
  for (let s = 0; s <= tmax + 1e-9; s += passo) {
    add('line', { class: 'eixo', x1: x(s), y1: y(0), x2: x(s), y2: y(0) + 5 });
    add('text', { x: x(s), y: y(0) + 20, 'text-anchor': 'middle' }, numeroBR(s));
  }
  add('text', { x: (ml + W - mr) / 2, y: H - 6, 'text-anchor': 'middle' }, 'tempo (s)');
  add('text', { x: 14, y: (mt + y(0)) / 2, 'text-anchor': 'middle', transform: `rotate(-90 14 ${(mt + y(0)) / 2})` }, 'velocidade');
  return svg;
}

/** Aviso no MEIO do quadro do gráfico (com pontinhos quando é "calculando"). */
function avisoNoQuadro(texto, comPontinhos) {
  const p = el('p', { className: 'ses-det-aviso' });
  if (comPontinhos) p.append(pontinhos());
  p.append(texto);
  return p;
}

async function preencherDetalhe() {
  const s = estado.sessao;
  const t = s.tentativas.find((x) => x.numero === detalheNumero);
  if (!t || (t.estado !== 'calculando' && t.estado !== 'concluida')) {
    $('detalhe').close();
    return;
  }

  $('det-titulo').textContent = `Tentativa ${t.numero} · ${s.paciente}`;
  $('det-alcance').textContent = textoAlcance(t.alcance);

  const dFlu = $('det-fluidez');
  dFlu.replaceChildren();
  if (t.estado === 'calculando') {
    dFlu.append(T.tentativa.calculando);
  } else {
    dFlu.append(T.fluidez[t.fluidez.nivel]);
    if (t.fluidez.nivel === 'indisponivel') dFlu.append(el('small', { textContent: T.motivoFluidez[t.fluidez.motivo] }));
  }

  const numeros = numerosComDetalhe();
  const i = numeros.indexOf(t.numero);
  $('det-anterior').disabled = i <= 0;
  $('det-proxima').disabled = i >= numeros.length - 1;
  $('det-anular').textContent = t.anulada ? T.acoes.restaurar : T.acoes.anular;

  // o quadro do gráfico só é refeito quando algo dele mudou (o estado chega a cada meio segundo)
  const chave = `${t.numero}|${t.estado}|${t.fluidez ? t.fluidez.nivel : ''}`;
  if (chave === detalheChave) return;
  detalheChave = chave;

  const area = $('det-curva');
  const legenda = $('det-legenda');
  legenda.textContent = '';
  if (t.estado === 'calculando') {
    area.replaceChildren(avisoNoQuadro(T.detalhe.calculando, true));
  } else if (t.fluidez.nivel === 'indisponivel') {
    area.replaceChildren(avisoNoQuadro(T.detalhe.semCurva[t.fluidez.motivo] || T.detalhe.semGrafico, false));
  } else {
    area.replaceChildren(avisoNoQuadro(T.detalhe.carregando, true));
    const curva = await obterCurva(t.numero);
    if (detalheNumero !== t.numero || detalheChave !== chave) return;   // o usuário já trocou de tentativa
    area.replaceChildren(curva ? desenharCurva(curva, t.numero) : avisoNoQuadro(T.detalhe.semGrafico, false));
    legenda.textContent = curva ? T.detalhe.legenda : '';
  }
}

function numerosComDetalhe() {
  return estado.sessao.tentativas
    .filter((x) => x.estado === 'calculando' || x.estado === 'concluida')
    .map((x) => x.numero)
    .sort((a, b) => a - b);
}

function irParaVizinha(passo) {
  const numeros = numerosComDetalhe();
  const novo = numeros[numeros.indexOf(detalheNumero) + passo];
  if (novo !== undefined) { detalheNumero = novo; preencherDetalhe(); }
}

function abrirDetalhe(numero) {
  detalheNumero = numero;
  detalheChave = null;
  preencherDetalhe();
  if (!$('detalhe').open) $('detalhe').showModal();
}

/* ---------- eventos da página ---------- */

function ligarEventos() {
  $('det-fechar').addEventListener('click', () => $('detalhe').close());
  $('detalhe').addEventListener('close', () => { detalheNumero = null; detalheChave = null; });
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

  const ta = $('com-texto');
  ta.addEventListener('input', () => {
    atualizarContador();
    estadoComentario('');
    clearTimeout(comTimer);
    comTimer = setTimeout(salvarComentario, 800);        // salva sozinho quando ela para de digitar
  });
  ta.addEventListener('blur', () => { if (comTimer !== null) salvarComentario(); });
  window.addEventListener('pagehide', () => { if (comTimer !== null) salvarComentario(); });

  // exportar: garante que o último comentário já foi salvo antes de abrir o relatório / baixar o CSV
  for (const id of ['b-pdf', 'b-csv']) {
    $(id).addEventListener('click', async (ev) => {
      if (comTimer === null && !comSalvando) return;     // nada pendente: segue o link normalmente
      ev.preventDefault();
      const alvo = $(id);
      await salvarPendente();
      if (id === 'b-pdf') window.open(alvo.href, '_blank', 'noopener');
      else location.href = alvo.href;
    });
  }

  $('b-concluir').addEventListener('click', async () => {      // "Encerrar" de uma sessão interrompida
    $('b-concluir').disabled = true;
    await salvarPendente();
    const r = await enviarComando('concluir_interrompida');
    $('b-concluir').disabled = false;
    if (!r.ok) mostrarErro(T.erros[r.erro] || T.erroGenerico(r.erro));
  });

  $('b-encerrar').addEventListener('click', async () => {
    if (!estado) return;
    if (estado.tela === 'sessao_encerrada') {          // "Fechar": sai do modo leitura e volta (ao histórico, se veio de lá)
      await salvarPendente();
      await enviarComando('fechar_leitura');
      location.href = veioDoHistorico ? app.dataset.urlHistorico : app.dataset.urlInicio;
      return;
    }
    $('b-encerrar').disabled = true;
    await salvarPendente();
    const r = await enviarComando('encerrar_sessao');
    if (!r.ok) {
      $('faixa-erro').hidden = false;
      $('faixa-erro').textContent = T.erros[r.erro] || T.erroGenerico(r.erro);
      $('b-encerrar').disabled = false;
    }
  });
}

/* ---------- partida ---------- */

$('aviso-js').hidden = true;             // se este módulo rodou, os scripts carregaram
iniciar();
ligarEventos();
assinar(renderizar);

// se em 2,5 s nenhum estado chegou, diz por quê (ex.: banco desatualizado = faltou rodar o migrate)
setTimeout(() => {
  if (estado) return;
  const erro = dados.ultimoErro;
  const motivo = erro ? (T.erros[erro] || erro) : '';
  mostrarErro(`${T.semEstado} ${motivo}`.trim());
}, 2500);