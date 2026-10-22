/* dados.js — ÚNICA porta de entrada de dados da tela (agora com o programa de verdade).

   A tela conhece só estas funções:
        iniciar(), assinar(fn), enviarComando(nome, args), obterCurva(numero)
   O estado que chega segue o contrato do Sandro (seção 12.3):
        { versao, servidor, tela, conta, equipamentos:{mesa,batedor}, sessao }
   Como o navegador não recebe UDP, o Django escuta as placas (receptor.py) e a tela PERGUNTA o estado
   a cada meio segundo (GET /api/estado/). Se um dia virar WebSocket, só este arquivo muda.

   Não há mais back de mentira nem simulador: sem circuito ligado, Mesa e Batedor aparecem "Sem sinal"
   e a Nova sessão fica esperando o aperto de 3 s (para testar sem a mesa, use tools/simular_placas.py). */

export const MODO_MOCK = false;
export const simulador = {};   // só para o sessao.js antigo continuar carregando; sai na etapa da Sessão

// Em produção isto vem de /api/config (por enquanto, as constantes do escopo do Sandro)
export const CONFIG = {
  versao_contrato: 1,
  bobinas_cm: [20, 27, 34, 41, 48, 55, 62, 69],
  gol_cm: 76,
};

const URL_ESTADO = '/api/estado/';
const URL_COMANDO = '/api/comando/';
const INTERVALO_MS = 500;

const ouvintes = new Set();
let estado = null;          // último estado válido
let servidor = null;
let rodando = false;
let semConexao = false;

const copia = (x) => JSON.parse(JSON.stringify(x));

function cookie(nome) {
  const m = document.cookie.split('; ').find((c) => c.startsWith(nome + '='));
  return m ? decodeURIComponent(m.split('=')[1]) : '';
}

function emitir() {
  if (!estado) return;
  const e = copia(estado);
  e.semConexao = semConexao;           // a tela mostra a faixa "Sem conexão com o programa"
  ouvintes.forEach((fn) => fn(e));
}

async function perguntar() {
  try {
    const r = await fetch(URL_ESTADO, { cache: 'no-store', credentials: 'same-origin' });
    if (r.status === 401) { location.reload(); return; }          // login expirou: volta para o login
    if (!r.ok) throw new Error(String(r.status));
    const novo = await r.json();
    // ignora estados mais velhos; se o servidor reiniciou ("servidor" mudou), aceita o novo
    if (!estado || novo.servidor !== servidor || novo.versao >= estado.versao) {
      servidor = novo.servidor;
      const mudou = !estado || JSON.stringify(novo) !== JSON.stringify(estado) || semConexao;
      estado = novo;
      semConexao = false;
      if (mudou) emitir();
    } else if (semConexao) {
      semConexao = false;
      emitir();
    }
  } catch (erro) {
    console.error('ESME: não consegui ler /api/estado/ —', erro);   // F12 > Console mostra o motivo
    if (!semConexao) { semConexao = true; emitir(); }
  }
}

async function laco() {
  await perguntar();
  setTimeout(laco, INTERVALO_MS);
}

/** Começa a perguntar o estado (só uma vez por página). */
export function iniciar() {
  if (rodando) return;
  rodando = true;
  laco();
}

/** Recebe o estado agora e a cada mudança. Devolve uma função para parar de ouvir. */
export function assinar(fn) {
  ouvintes.add(fn);
  if (estado) { const e = copia(estado); e.semConexao = semConexao; fn(e); }
  return () => ouvintes.delete(fn);
}

/** Comandos: 'preparar_sessao', 'cancelar_espera', 'sugestoes_nome', 'encerrar_sessao' (os outros entram com a Sessão).
    Devolve { ok: true, ... } ou { ok: false, erro: 'codigo' }. */
export async function enviarComando(nome, args = {}) {
  try {
    const r = await fetch(URL_COMANDO, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': cookie('csrftoken') },
      body: JSON.stringify({ nome, args }),
    });
    const dados = await r.json().catch(() => ({ ok: false, erro: 'pedido_invalido' }));
    if (dados.ok && nome !== 'sugestoes_nome') perguntar();       // atualiza a tela sem esperar o próximo ciclo
    return dados;
  } catch {
    return { ok: false, erro: 'sem_conexao' };
  }
}

/** Curva de velocidade de uma tentativa (etapa da Sessão). */
export async function obterCurva() {
  return null;
}