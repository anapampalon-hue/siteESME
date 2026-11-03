/* configuracoes.js — página "Configurar mesa e batedor": 4 passos (Rede → Placa da mesa → Placa do batedor → Conferir).
   A SENHA do Wi-Fi fica só numa variável desta página (memória do navegador): não vai para localStorage, cookie nem URL,
   é enviada ao programa só na hora de gravar na placa, e some quando se chega ao passo 4.
   Texto vindo de fora (nome de rede, interface) entra só por textContent. */

import { T } from './textos.js?v=4';
import * as dados from './dados.js?v=4';

const { iniciar, assinar, enviarComando } = dados;
const $ = (id) => document.getElementById(id);
const app = $('app');
$('aviso-js').hidden = true;

const dado = {
  ssidAtual: null,         // Wi-Fi em que o notebook está agora (se o programa conseguiu ler)
  ssid: '', ip: '', senha: '',        // o que foi digitado no passo 1 (a senha só existe aqui)
  bloqueada: false, pyserial: true,
  gravado: { MESA: false, BATEDOR: false },
  equipamentos: { mesa: 'sem_sinal', batedor: 'sem_sinal' },
};
let passo = 1;
let ficha = 0;               // numera as rodadas de procura de placa (para ignorar resposta atrasada)
let gravando = false;
let forcarProxima = false;
let temporizadorDicas = null;

const el = (tag, props = {}, ...filhos) => { const e = document.createElement(tag); Object.assign(e, props); e.append(...filhos); return e; };
const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
const painel = (n) => document.querySelector(`[data-painel="${n}"]`);
const frase = (c) => T.config.erros[c] || T.erros[c] || T.erroGenerico(c);
const pontinhos = () => { const p = el('span', { className: 'cfg-pontinhos' }, el('i'), el('i'), el('i')); p.setAttribute('aria-hidden', 'true'); return p; };

function faixa(texto) {
  $('faixa-erro').hidden = !texto;
  $('faixa-erro').textContent = texto || '';
}

/* ---------- passos ---------- */
function irPara(n) {
  passo = n;
  ficha++;                                   // para a procura de placas do passo anterior
  document.querySelectorAll('[data-painel]').forEach((p) => { p.hidden = Number(p.dataset.painel) !== n; });
  document.querySelectorAll('#passos li').forEach((li) => {
    const k = Number(li.dataset.passo);
    if (k === n) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
    li.classList.toggle('feito', k < n);
  });
  clearTimeout(temporizadorDicas);
  $('c-dicas').hidden = true;
  if (n === 2 || n === 3) iniciarProcura(n);
  if (n === 4) {
    dado.senha = '';                         // a senha já cumpriu seu papel: esquece
    $('c-senha').value = '';
    temporizadorDicas = setTimeout(() => { $('c-dicas').hidden = false; }, 20000);
    renderConferir();
  }
}

/* ---------- passo 1: rede ---------- */
function preencherRede(r) {
  dado.ssidAtual = r.ssid_atual || null;
  dado.pyserial = r.pyserial;
  dado.bloqueada = r.bloqueada;
  if (!$('c-ssid').value) $('c-ssid').value = r.configurada && r.configurada.ssid ? r.configurada.ssid : (r.ssid_atual || '');
  const select = $('c-ip');
  select.replaceChildren(...r.ips.map((c) => el('option', { value: c.ip, textContent: c.interface ? `${c.ip} (${c.interface})` : c.ip })));
  if (r.ip_sugerido) select.value = r.ip_sugerido;
  $('c-ip-ajuda').textContent = r.ips.length === 0 ? T.config.semRede : r.ips.length === 1 ? T.config.ajudaIpUm : T.config.ajudaIpVarios;
  if (r.bloqueada) faixa(T.config.erros.sessao_aberta);
  else if (!r.pyserial) faixa(T.config.erros.pyserial_ausente);
}

function mostrarErro1(texto) {
  $('c-erro-1').hidden = !texto;
  $('c-erro-1').textContent = texto || '';
}

function continuarPasso1() {
  mostrarErro1('');
  const ssid = $('c-ssid').value.trim();
  const senha = $('c-senha').value;
  const ip = $('c-ip').value;
  $('c-ssid').removeAttribute('aria-invalid');
  $('c-senha').removeAttribute('aria-invalid');
  if (dado.bloqueada) return mostrarErro1(T.config.erros.sessao_aberta);
  if (!ssid || new TextEncoder().encode(ssid).length > 32) { $('c-ssid').setAttribute('aria-invalid', 'true'); $('c-ssid').focus(); return mostrarErro1(T.config.erroSsid); }
  if (senha !== '' && (senha.length < 8 || senha.length > 63)) { $('c-senha').setAttribute('aria-invalid', 'true'); $('c-senha').focus(); return mostrarErro1(T.config.erroSenha); }
  if (!ip) return mostrarErro1(ip === '' && $('c-ip').options.length === 0 ? T.config.semRede : T.config.erroIp);
  if (dado.ssidAtual && dado.ssidAtual !== ssid) return mostrarErro1(T.config.redeDiferente(dado.ssidAtual, ssid));
  Object.assign(dado, { ssid, senha, ip });
  irPara(2);
}

/* ---------- passos 2 e 3: placa ligada por USB ---------- */
const tipoDoPasso = (n) => painel(n).dataset.tipo;
const botaoDe = (n, acao) => painel(n).querySelector(`[data-acao="${acao}"]`);

function definirStatus(n, ...partes) {
  painel(n).querySelector('.cfg-status').replaceChildren(...partes);
}

function definirResultado(n, texto, classe = '', comPontinhos = false) {
  const r = painel(n).querySelector('.cfg-resultado');
  r.className = `cfg-resultado ${classe}`.trim();
  r.replaceChildren(...(comPontinhos ? [pontinhos()] : []), texto);
}

function atualizarBotoes(n, { podeGravar, mostrarProcurar }) {
  botaoDe(n, 'gravar').disabled = !podeGravar || gravando || dado.bloqueada;
  botaoDe(n, 'procurar').hidden = !mostrarProcurar;
  botaoDe(n, 'continuar').disabled = !dado.gravado[tipoDoPasso(n)] || gravando;
  botaoDe(n, 'voltar').disabled = gravando;
  const chave = tipoDoPasso(n) === 'MESA' ? 'mesa' : 'batedor';
  botaoDe(n, 'pular').hidden = !(dado.equipamentos[chave] === 'ok' && !dado.gravado[tipoDoPasso(n)]) || gravando;
}

function renderPlacas(n, r) {
  const esperada = tipoDoPasso(n);
  if (!r.ok) {
    definirStatus(n, frase(r.erro));
    atualizarBotoes(n, { podeGravar: false, mostrarProcurar: true });
    return;
  }
  const placas = r.placas;
  if (placas.length === 0) {
    definirStatus(n, T.config.nenhuma);
    return atualizarBotoes(n, { podeGravar: false, mostrarProcurar: false });
  }
  if (placas.length > 1) {
    definirStatus(n, T.config.varias(esperada));
    return atualizarBotoes(n, { podeGravar: false, mostrarProcurar: true });
  }
  const p = placas[0];
  if (!p.tipo) {
    definirStatus(n, frase(p.erro || 'sem_resposta'));
    return atualizarBotoes(n, { podeGravar: false, mostrarProcurar: true });
  }
  const achada = el('span', {}, T.config.encontrada, ' ', el('strong', { textContent: p.tipo }), T.config.versao(p.versao));
  if (p.tipo !== esperada) {
    definirStatus(n, achada, ` · ${T.config.tipoErrado(esperada)}`);
    return atualizarBotoes(n, { podeGravar: false, mostrarProcurar: true });
  }
  definirStatus(n, achada);
  atualizarBotoes(n, { podeGravar: true, mostrarProcurar: false });
}

async function iniciarProcura(n) {
  const minha = ++ficha;
  definirStatus(n, T.config.procurando);
  atualizarBotoes(n, { podeGravar: false, mostrarProcurar: false });
  if (!dado.gravado[tipoDoPasso(n)]) definirResultado(n, '');
  while (minha === ficha && (passo === 2 || passo === 3)) {
    if (!gravando) {
      const r = await enviarComando('config_placas', { forcar: forcarProxima });
      forcarProxima = false;
      if (minha !== ficha) return;
      if (!gravando) renderPlacas(n, r);
    }
    await esperar(1500);
  }
}

async function gravar(n) {
  const tipo = tipoDoPasso(n);
  gravando = true;
  atualizarBotoes(n, { podeGravar: false, mostrarProcurar: false });
  definirResultado(n, T.config.gravando, '', true);
  const r = await enviarComando('config_gravar', { tipo, ssid: dado.ssid, senha: dado.senha, ip: dado.ip });
  gravando = false;
  if (r.ok) {
    dado.gravado[tipo] = true;
    definirResultado(n, T.config.gravado, 'ok');
    atualizarBotoes(n, { podeGravar: true, mostrarProcurar: false });
  } else {
    definirResultado(n, frase(r.erro), 'erro');
    atualizarBotoes(n, { podeGravar: false, mostrarProcurar: true });
    forcarProxima = true;
  }
}

function pular(n) {
  dado.gravado[tipoDoPasso(n)] = true;
  definirResultado(n, T.config.pulada, 'ok');
  atualizarBotoes(n, { podeGravar: false, mostrarProcurar: false });
}

/* ---------- passo 4: conferir ---------- */
function renderConferir() {
  const linha = (id, ok, rotuloOk) => {
    $(id).querySelector('span').textContent = ok ? rotuloOk : T.config.semSinal;
  };
  linha('conf-mesa', dado.equipamentos.mesa === 'ok', T.config.conectada);
  linha('conf-batedor', dado.equipamentos.batedor === 'ok', T.config.conectado);
  const tudo = dado.equipamentos.mesa === 'ok' && dado.equipamentos.batedor === 'ok';
  $('c-conferido').hidden = !tudo;
  $('c-conferido').textContent = tudo ? T.config.duasOk : '';
  $('b-concluir').disabled = !tudo;
}

async function concluir() {
  $('c-erro-4').hidden = true;
  $('b-concluir').disabled = true;
  const r = await enviarComando('config_concluir', { ssid: dado.ssid, ip: dado.ip });
  if (r.ok) { location.href = app.dataset.urlInicio; return; }
  $('c-erro-4').hidden = false;
  $('c-erro-4').textContent = frase(r.erro);
  renderConferir();
}

/* ---------- sinais da mesa e do batedor (cabeçalho) ---------- */
function indicador(elemento, valor, textos) {
  elemento.dataset.estado = valor;
  elemento.querySelector('.ind-texto').textContent = textos[valor];
}

function aoReceberEstado(e) {
  if (e.semConexao) faixa(T.semConexao);
  else if (!dado.bloqueada && dado.pyserial) faixa('');
  indicador($('ind-mesa'), e.equipamentos.mesa, T.mesa);
  indicador($('ind-batedor'), e.equipamentos.batedor, T.batedor);
  dado.equipamentos = e.equipamentos;
  if (passo === 4) renderConferir();
  if (passo === 2 || passo === 3) atualizarBotoes(passo, {
    podeGravar: !botaoDe(passo, 'gravar').disabled, mostrarProcurar: !botaoDe(passo, 'procurar').hidden,
  });
}

/* ---------- eventos ---------- */
function ligarEventos() {
  $('c-mostrar').addEventListener('change', (ev) => { $('c-senha').type = ev.target.checked ? 'text' : 'password'; });
  $('b-continuar-1').addEventListener('click', continuarPasso1);
  [2, 3].forEach((n) => {
    botaoDe(n, 'gravar').addEventListener('click', () => gravar(n));
    botaoDe(n, 'procurar').addEventListener('click', () => { forcarProxima = true; definirStatus(n, T.config.procurando); });
    botaoDe(n, 'pular').addEventListener('click', () => pular(n));
    botaoDe(n, 'voltar').addEventListener('click', () => irPara(n - 1));
    botaoDe(n, 'continuar').addEventListener('click', () => irPara(n + 1));
  });
  painel(4).querySelector('[data-acao="voltar"]').addEventListener('click', () => irPara(3));
  $('b-concluir').addEventListener('click', concluir);
  window.addEventListener('pagehide', () => { dado.senha = ''; });
}

/* ---------- partida ---------- */
(async function partir() {
  ligarEventos();
  irPara(1);
  iniciar();
  assinar(aoReceberEstado);
  const r = await enviarComando('config_estado');
  if (r.ok) preencherRede(r);
  else faixa(frase(r.erro));
})();