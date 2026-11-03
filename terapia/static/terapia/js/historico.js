/* historico.js — página do Histórico: lista as sessões salvas (pedindo ao programa, nunca guardando nada no navegador).
   PSEUDONIMIZAÇÃO: a lista mostra só o CÓDIGO do paciente (P-XXXXXX). O nome só chega do programa se a terapeuta
   marcar "Mostrar nomes". Texto vindo de fora entra sempre por textContent (nunca innerHTML). */

import { T } from './textos.js?v=4';
import { enviarComando } from './dados.js?v=4';

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
function cabecalho(comFisio, comNome) {
  const colunas = [T.historico.colData, comNome ? T.historico.colPaciente : T.historico.colCodigo];
  if (comNome) colunas.push(T.historico.colCodigo);
  if (comFisio) colunas.push(T.historico.colFisio);
  colunas.push(T.historico.colValidas, T.historico.colMelhor, T.historico.colStatus, T.historico.colAcoes);
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

function linha(s, comFisio, comNome) {
  const tr = el('tr');
  tr.append(el('td', { textContent: `${dataBR(s.data)}${s.inicio ? ` · ${horaBR(s.inicio)}` : ''}` }));
  if (comNome) tr.append(el('td', { className: 'his-nome', textContent: s.nome || '' }));
  tr.append(el('td', { className: 'his-codigo', textContent: s.codigo }));
  if (comFisio) tr.append(el('td', { textContent: s.fisio || '' }));
  tr.append(el('td', { textContent: s.tentativas_validas }));
  tr.append(el('td', { textContent: textoAlcance(s.melhor_alcance) }));

  const tdStatus = el('td', {}, el('span', { className: `his-estado his-estado-${s.status}`, textContent: T.historico.status[s.status] }));
  if (s.tem_comentario) tdStatus.append(el('small', { textContent: T.historico.comComentario }));
  tr.append(tdStatus);

  const abrirBtn = el('button', { type: 'button', className: 'botao botao-claro his-btn', textContent: T.historico.abrir, onclick: () => abrir(s.id) });
  const pdf = el('a', { className: 'botao botao-claro his-btn', textContent: T.historico.pdf, target: '_blank', rel: 'noopener', href: urlCom(app.dataset.urlRelatorio, s.id) });
  const csv = el('a', { className: 'botao botao-claro his-btn', textContent: T.historico.csv, href: urlCom(app.dataset.urlCsv, s.id) });
  tr.append(el('td', { className: 'his-acoes' }, abrirBtn, pdf, csv));
  return tr;
}

function desenhar(sessoes, filtrando, comNome) {
  const comFisio = sessoes.some((s) => s.fisio);
  cabecalho(comFisio, comNome);
  $('lista').replaceChildren(...sessoes.map((s) => linha(s, comFisio, comNome)));
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
  desenhar(r.sessoes, Boolean(busca || dataISO), revelar);
  $('f-dica').textContent = revelar ? T.historico.dicaNomes : T.historico.dicaCodigos;
}

/* ---------- eventos ---------- */
$('filtros').addEventListener('submit', (ev) => ev.preventDefault());
campoBusca.addEventListener('input', () => { clearTimeout(espera); espera = setTimeout(carregar, 250); });
campoData.addEventListener('input', () => { clearTimeout(espera); espera = setTimeout(carregar, 250); });
caixaNomes.addEventListener('change', carregar);
$('f-limpar').addEventListener('click', () => {
  campoBusca.value = '';
  campoData.value = '';
  carregar();
});

carregar();