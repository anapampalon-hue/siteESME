/* historico.js — página do Histórico: lista as sessões salvas (pedindo ao programa, nunca guardando nada no navegador).
   PSEUDONIMIZAÇÃO: a lista mostra só o CÓDIGO do paciente (P-XXXXXX). O nome só chega do programa se a terapeuta
   marcar "Mostrar nomes". Texto vindo de fora entra sempre por textContent (nunca innerHTML). */

import { T } from './textos.js?v=7';
import { enviarComando } from './dados.js?v=6';

const $ = (id) => document.getElementById(id);
const app = $('app');
$('aviso-js').hidden = true;

const campoBusca = $('f-busca');
const campoData = $('f-data');
const caixaNomes = $('f-nomes');

let pedido = 0;            // numera os pedidos: resposta atrasada é ignorada
let espera = null;         // temporizador da busca (digitando)

function el(tag, props = {}, ...filhos) {
  const e = document.createElement(tag);
  Object.assign(e, props);
  e.append(...filhos);
  return e;
}

const dataBR = (iso) => (iso ? iso.split('-').reverse().join('/') : '');
const horaBR = (iso) => (iso ? new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '');
const urlCom = (modelo, id) => modelo.replace('/0/', `/${id}/`).replace(/\/0$/, `/${id}`);

function textoAlcance(a) {
  if (!a || a.cm == null) return T.alcanceNenhum;
  return a.gol ? `${a.cm} cm (gol)` : `${a.cm} cm (bobina ${a.bobina})`;
}

function mostrarErro(texto) {
  $('faixa-erro').hidden = !texto;
  $('faixa-erro').textContent = texto || '';
}

/* ---------- filtro de data (a mesma máscara da Nova sessão) ---------- */
campoData.addEventListener('input', () => {
  const d = campoData.value.replace(/\D/g, '').slice(0, 8);
  if (d.length > 4) campoData.value = `${d.slice(0, 2)}/${d.slice(2, 4)}/${d.slice(4)}`;
  else if (d.length > 2) campoData.value = `${d.slice(0, 2)}/${d.slice(2)}`;
  else campoData.value = d;
});

/** 'dd/mm/aaaa' -> 'aaaa-mm-dd' (ou null se não existir essa data) */
function dataValida(texto) {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(texto);
  if (!m) return null;
  const dia = Number(m[1]), mes = Number(m[2]), ano = Number(m[3]);
  const d = new Date(ano, mes - 1, dia);
  if (ano < 2000 || d.getFullYear() !== ano || d.getMonth() !== mes - 1 || d.getDate() !== dia) return null;
  return `${m[3]}-${m[2]}-${m[1]}`;
}

/* ---------- tabela ---------- */
function cabecalho(ctx) {
  const colunas = [T.historico.colData, ctx.comNome ? T.historico.colPaciente : T.historico.colCodigo];
  if (ctx.comNome) colunas.push(T.historico.colCodigo);
  if (ctx.comFisio) colunas.push(T.historico.colFisio);
  colunas.push(T.historico.colTentativas, T.historico.colAcoes);
  $('cabecalho').replaceChildren(...colunas.map((c) => el('th', { scope: 'col', textContent: c })));
}

async function abrir(id) {
  mostrarErro('');
  const r = await enviarComando('abrir_sessao', { id });
  if (!r.ok) {
    mostrarErro(r.erro === 'sessao_aberta' ? T.historico.erroAbrirComSessao : (T.erros[r.erro] || T.erroGenerico(r.erro)));
    return;
  }
  location.href = `${app.dataset.urlSessao}?de=historico`;
}

/* ---------- excluir (só a supervisora; o servidor confere de novo) ---------- */
let excluindoId = null;

function pedirExclusao(s) {
  excluindoId = s.id;
  $('excluir-titulo').textContent = T.historico.excluirTitulo;
  $('excluir-texto').textContent = T.historico.excluirTexto(s.codigo, dataBR(s.data));
  $('excluir-cancelar').textContent = T.historico.excluirCancelar;
  $('excluir-confirmar').textContent = T.historico.excluirConfirmar;
  $('excluir-confirmar').disabled = false;
  $('excluir-erro').hidden = true;
  $('excluir-dialogo').showModal();
  $('excluir-cancelar').focus();                 // o foco começa no "Cancelar": excluir exige um gesto deliberado
}

async function confirmarExclusao() {
  if (excluindoId === null) return;
  $('excluir-confirmar').disabled = true;
  $('excluir-confirmar').textContent = T.historico.excluindo;
  const r = await enviarComando('excluir_sessao', { id: excluindoId });
  if (!r.ok) {
    $('excluir-confirmar').disabled = false;
    $('excluir-confirmar').textContent = T.historico.excluirConfirmar;
    $('excluir-erro').hidden = false;
    $('excluir-erro').textContent = T.erros[r.erro] || T.erroGenerico(r.erro);
    return;
  }
  excluindoId = null;
  $('excluir-dialogo').close();
  carregar();
}

/* ---------- transferir (só a supervisora; o servidor confere de novo) ---------- */
let transferindo = null;          // a linha (sessão) da janela aberta
let destinosAtuais = [];

const escolhido = (nome) => document.querySelector(`input[name="${nome}"]:checked`).value;

function pedirTransferencia(s) {
  transferindo = s;
  const outras = destinosAtuais.filter((d) => d.id !== s.fisio_id);
  const quem = s.realizada_por || s.fisio;
  $('transf-titulo').textContent = T.historico.transferirTitulo;
  $('transf-resumo').textContent = T.historico.transferirResumo(s.codigo, dataBR(s.data), quem);
  const varias = (s.n_paciente || 1) > 1;
  $('op-paciente').hidden = !varias;
  document.querySelector('input[name="transf-escopo"][value="paciente"]').checked = varias;
  document.querySelector('input[name="transf-escopo"][value="sessao"]').checked = !varias;
  $('op-paciente-t').textContent = T.historico.escopoPaciente;
  $('op-paciente-a').textContent = T.historico.escopoPacienteAjuda(s.n_paciente || 1);
  $('op-sessao-t').textContent = T.historico.escopoSessao;
  $('op-sessao-a').textContent = varias ? T.historico.escopoSessaoAjuda : '';
  $('autora-pergunta').textContent = T.historico.autoraPergunta(s.fisio);
  $('autora-sim').textContent = T.historico.autoraMantem(s.fisio);
  $('autora-nao').textContent = T.historico.autoraSai(s.fisio);
  document.querySelector('input[name="transf-autora"][value="sim"]').checked = true;
  $('transf-destino-rotulo').textContent = outras.length ? T.historico.destino : T.historico.destinoVazio;
  $('transf-destino').replaceChildren(...outras.map((d) => el('option', { value: d.id, textContent: d.nome })));
  $('transf-destino').disabled = outras.length === 0;
  $('transf-cancelar').textContent = T.historico.excluirCancelar;
  $('transf-confirmar').textContent = T.historico.transferirConfirmar;
  $('transf-confirmar').disabled = outras.length === 0;
  $('transf-erro').hidden = true;
  $('transf-dialogo').showModal();
}

async function confirmarTransferencia() {
  if (!transferindo) return;
  $('transf-confirmar').disabled = true;
  $('transf-confirmar').textContent = T.historico.transferindo;
  const r = await enviarComando('transferir_sessao', {
    id: transferindo.id, destino: Number($('transf-destino').value),
    escopo: escolhido('transf-escopo'), autora_ve: escolhido('transf-autora') === 'sim',
  });
  $('transf-confirmar').textContent = T.historico.transferirConfirmar;
  if (!r.ok) {
    $('transf-confirmar').disabled = false;
    $('transf-erro').hidden = false;
    $('transf-erro').textContent = r.erro === 'sessao_aberta' ? T.historico.erroAbrirComSessao : (T.erros[r.erro] || T.erroGenerico(r.erro));
    return;
  }
  transferindo = null;
  $('transf-dialogo').close();
  carregar();
}

/* ---------- menu "⋯" das ações (um só, colocado ao lado do botão que o abriu) ---------- */
const menu = $('his-menu');
let menuDe = null;

function fecharMenu() {
  menu.hidden = true;
  if (menuDe) menuDe.setAttribute('aria-expanded', 'false');
  menuDe = null;
}

function itemMenu(texto, props = {}, perigo = false) {
  const tag = props.href ? 'a' : 'button';
  const it = el(tag, { className: `his-menu-item${perigo ? ' his-menu-perigo' : ''}`, textContent: texto, ...props });
  if (tag === 'button') it.type = 'button';
  it.setAttribute('role', 'menuitem');
  return it;
}

function abrirMenu(botao, s, ctx) {
  if (menuDe === botao) { fecharMenu(); return; }
  fecharMenu();
  const itens = [
    itemMenu(T.historico.pdf, { href: urlCom(app.dataset.urlRelatorio, s.id), target: '_blank', rel: 'noopener' }),
    itemMenu(T.historico.csv, { href: urlCom(app.dataset.urlCsv, s.id) }),
  ];
  if (ctx.podeTransferir || ctx.podeExcluir) itens.push(el('div', { className: 'his-menu-sep', role: 'separator' }));
  if (ctx.podeTransferir) itens.push(itemMenu(T.historico.transferir, { onclick: () => { fecharMenu(); pedirTransferencia(s); } }));
  if (ctx.podeExcluir) itens.push(itemMenu(T.historico.excluir, { onclick: () => { fecharMenu(); pedirExclusao(s); } }, true));
  menu.replaceChildren(...itens);
  menu.hidden = false;
  const r = botao.getBoundingClientRect();
  const m = menu.getBoundingClientRect();
  const abaixo = r.bottom + 6 + m.height <= window.innerHeight - 8;
  menu.style.top = `${abaixo ? r.bottom + 6 : Math.max(8, r.top - m.height - 6)}px`;
  menu.style.left = `${Math.max(8, r.right - m.width)}px`;
  botao.setAttribute('aria-expanded', 'true');
  menuDe = botao;
  itens[0].focus();
}

document.addEventListener('click', (ev) => { if (menuDe && !menu.contains(ev.target) && !menuDe.contains(ev.target)) fecharMenu(); });
document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && menuDe) { const b = menuDe; fecharMenu(); b.focus(); } });
window.addEventListener('resize', fecharMenu);
window.addEventListener('scroll', fecharMenu, true);

/* ---------- linhas ---------- */
const NS = 'http://www.w3.org/2000/svg';
function iconeMais() {
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  [5, 12, 19].forEach((x) => {
    const c = document.createElementNS(NS, 'circle');
    c.setAttribute('cx', x); c.setAttribute('cy', 12); c.setAttribute('r', 1.6);
    svg.append(c);
  });
  return svg;
}

function linha(s, ctx) {
  const tr = el('tr');
  const quando = el('td', {}, `${dataBR(s.data)}${s.inicio ? ` · ${horaBR(s.inicio)}` : ''}`);
  if (s.status === 'interrompida') quando.append(el('br'), el('span', { className: 'his-etiqueta-int', textContent: T.historico.interrompida }));
  tr.append(quando);
  if (ctx.comNome) tr.append(el('td', { className: 'his-nome', textContent: s.nome || '' }));
  const tdCodigo = el('td', { className: 'his-codigo', textContent: s.codigo });
  tr.append(tdCodigo);
  if (ctx.comFisio) {
    const tdFisio = el('td', {}, s.fisio || '');
    // a terapeuta que só consulta vê "somente consulta"; quem edita (e a supervisora) vê quem realizou
    if (s.somente_consulta && !ctx.podeTransferir) tdFisio.append(el('br'), el('span', { className: 'his-etiqueta', textContent: T.historico.somenteConsulta }));
    else if (s.realizada_por) tdFisio.append(el('br'), el('span', { className: 'his-etiqueta', textContent: T.historico.realizadaPor(s.realizada_por) }));
    tr.append(tdFisio);
  }
  tr.append(el('td', {}, String(s.tentativas_validas), el('small', { textContent: T.historico.melhor(textoAlcance(s.melhor_alcance)) })));

  const abrirBtn = el('button', { type: 'button', className: 'botao his-btn his-abrir', textContent: T.historico.abrir, onclick: () => abrir(s.id) });
  const mais = el('button', { type: 'button', className: 'btn-quadrado his-mais', title: T.historico.maisAcoes }, iconeMais());
  mais.setAttribute('aria-label', T.historico.maisAcoes);
  mais.setAttribute('aria-haspopup', 'menu');
  mais.setAttribute('aria-expanded', 'false');
  mais.addEventListener('click', () => abrirMenu(mais, s, ctx));
  tr.append(el('td', { className: 'his-acoes' }, el('div', { className: 'his-acoes-linha' }, abrirBtn, mais)));
  return tr;
}

function desenhar(sessoes, filtrando, comNome, extras) {
  const ctx = { comNome, comFisio: sessoes.some((s) => s.fisio), ...extras };
  cabecalho(ctx);
  fecharMenu();
  $('lista').replaceChildren(...sessoes.map((s) => linha(s, ctx)));
  $('tabela').hidden = sessoes.length === 0;
  $('vazio').hidden = sessoes.length > 0;
  $('vazio').textContent = filtrando ? T.historico.nadaEncontrado : T.historico.vazio;
}

/* ---------- pedir a lista ao programa ---------- */
async function carregar() {
  const busca = campoBusca.value.trim();
  const textoData = campoData.value.trim();
  const dataISO = textoData.length === 10 ? dataValida(textoData) : null;

  const erroData = textoData.length === 10 && !dataISO;
  campoData.setAttribute('aria-invalid', erroData ? 'true' : 'false');
  $('f-erro').hidden = !erroData;
  $('f-erro').textContent = erroData ? T.novaSessao.erroData : '';
  if (erroData) return;                                     // espera a data ficar certa

  const meu = ++pedido;
  const revelar = caixaNomes.checked;
  const r = await enviarComando('listar_historico', { busca, data: dataISO || '', revelar });
  if (meu !== pedido) return;                               // chegou uma resposta mais nova
  if (!r.ok) {
    mostrarErro(r.erro === 'sem_conexao' ? T.semConexao : (T.erros[r.erro] || T.erroGenerico(r.erro)));
    return;
  }
  mostrarErro('');
  destinosAtuais = r.destinos || [];
  desenhar(r.sessoes, Boolean(busca || dataISO), revelar, { podeExcluir: Boolean(r.pode_excluir), podeTransferir: Boolean(r.pode_transferir) });
  $('f-dica').textContent = revelar ? T.historico.dicaNomes : T.historico.dicaCodigos;
}

/* ---------- eventos ---------- */
$('filtros').addEventListener('submit', (ev) => ev.preventDefault());
campoBusca.addEventListener('input', () => { clearTimeout(espera); espera = setTimeout(carregar, 250); });
campoData.addEventListener('input', () => { clearTimeout(espera); espera = setTimeout(carregar, 250); });
caixaNomes.addEventListener('change', carregar);
$('excluir-cancelar').addEventListener('click', () => $('excluir-dialogo').close());
$('excluir-confirmar').addEventListener('click', confirmarExclusao);
$('transf-cancelar').addEventListener('click', () => $('transf-dialogo').close());
$('transf-x').addEventListener('click', () => $('transf-dialogo').close());
$('transf-confirmar').addEventListener('click', confirmarTransferencia);
$('f-limpar').addEventListener('click', () => {
  campoBusca.value = '';
  campoData.value = '';
  carregar();
});

carregar();