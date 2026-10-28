/* nova_sessao.js — página "Nova sessão" (seção 7.5 do escopo do Sandro): nome do paciente + data. Depois de "Continuar", vai para a página de espera da mesa (espera_mesa.js).

*/

import { T } from './textos.js';
import { iniciar, assinar, enviarComando } from './dados.js';

const $ = (id) => document.getElementById(id);
const app = $('app');
$('aviso-js').hidden = true;      // se o script chegou até aqui, o aviso de "scripts não carregaram" some
const form = $('form-nova');
const campoNome = $('paciente');
const campoData = $('data');
const erro = $('erro-nova');
const lista = $('nomes-usados');
const faixa = $('faixa-erro');
const caixaTcle = $('tcle');

/* ---------- TCLE virtual ----------
   Marcado: nome e data valem (como sempre). Desmarcado: o nome vira "Anônimo", a data 00/00/0000 e os campos travam;
   o programa guarda a sessão só até ela ser fechada. O que a terapeuta já digitou volta se ela marcar de novo. */
let digitado = { nome: '', data: '' };
function aplicarTcle(foco) {
  const aceito = caixaTcle.checked;
  if (!aceito && !campoNome.disabled) digitado = { nome: campoNome.value, data: campoData.value };
  if (aceito) { campoNome.value = digitado.nome; campoData.value = digitado.data; }
  else { campoNome.value = T.novaSessao.anonimo; campoData.value = T.novaSessao.dataAnonima; }
  campoNome.disabled = campoData.disabled = !aceito;
  limparErro();
  if (aceito && foco) campoNome.focus();
}
caixaTcle.addEventListener('change', () => aplicarTcle(true));

/* ---------- máscara e validação da data (a caixa começa vazia; o programa não preenche) ---------- */
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

function mostrarErro(mensagem, campo) {
  erro.textContent = mensagem;
  erro.hidden = false;
  if (campo) { campo.setAttribute('aria-invalid', 'true'); campo.focus(); }
}
function limparErro() {
  erro.hidden = true;
  campoNome.removeAttribute('aria-invalid');
  campoData.removeAttribute('aria-invalid');
}
const frase = (codigo) => T.erros[codigo] || T.erroGenerico(codigo);

/* ---------- sugestões: nomes que ESTE fisioterapeuta já usou (vêm do programa, nunca do navegador) ---------- */
let pedidoSug = 0;
let esperaSug = null;
campoNome.addEventListener('input', () => {
  clearTimeout(esperaSug);
  if (campoNome.disabled) return;
  esperaSug = setTimeout(async () => {
    const meu = ++pedidoSug;
    const r = await enviarComando('sugestoes_nome', { prefixo: campoNome.value });
    if (meu !== pedidoSug || !r.ok) return;                 // resposta atrasada: ignora
    lista.replaceChildren(...r.nomes.map((n) => { const o = document.createElement('option'); o.value = n; return o; }));
  }, 200);
});

/* ---------- enviar ---------- */
form.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  limparErro();
  const aceito = caixaTcle.checked;
  let nome = '', dataISO = '';
  if (aceito) {
    nome = campoNome.value.trim().replace(/\s+/g, ' ');
    if (!nome) return mostrarErro(T.novaSessao.erroNome, campoNome);
    dataISO = dataValida(campoData.value.trim());
    if (!dataISO) return mostrarErro(T.novaSessao.erroData, campoData);
  }

  const botao = $('b-continuar');
  botao.disabled = true;
  // sem o "check" do TCLE o programa ignora nome e data: a sessão é anônima
  const r = await enviarComando('preparar_sessao', { paciente: nome, data: dataISO, consentimento: aceito });
  botao.disabled = false;
  if (!r.ok) return mostrarErro(frase(r.erro));
  location.href = app.dataset.espera;                       // segue para a página de espera da mesa
});

aplicarTcle(false);      // começa desmarcado (o navegador pode ter lembrado a caixa de uma visita anterior)

/* ---------- segue o estado do programa ---------- */
function indicador(id, quem, valor) {
  const el = $(id);
  el.dataset.estado = valor;
  el.querySelector('.ind-texto').textContent =
    valor === 'ok' ? T[quem].ok : `${T[quem].sem_sinal} · ${T.avisoSemSinal[quem]}`;
}

assinar((e) => {
  faixa.hidden = !e.semConexao;
  faixa.textContent = T.semConexao;
  indicador('ind-mesa', 'mesa', e.equipamentos.mesa);
  indicador('ind-batedor', 'batedor', e.equipamentos.batedor);

  if (e.tela === 'aguardando_mesa') { location.href = app.dataset.espera; return; }       // F5 no meio da espera
  if (e.tela === 'sessao_em_andamento') { location.href = app.dataset.sessao; return; }   // já há sessão aberta
});
iniciar();