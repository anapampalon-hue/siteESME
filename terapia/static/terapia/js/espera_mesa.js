/* espera_mesa.js — página "Aguardando a mesa" (seção 7.6 do escopo do Sandro).
   Mostra paciente + sinal da mesa e do batedor e espera o aperto de 3 s do botão "nova sessão".
   Quem manda é o estado do programa:
     aguardando_mesa     -> fica aqui
     sessao_em_andamento -> vai para a página da Sessão
     sem_sessao          -> volta para a Nova sessão (ex.: depois de Cancelar) */

import { T } from './textos.js';
import { iniciar, assinar, enviarComando } from './dados.js';

const $ = (id) => document.getElementById(id);
const app = $('app');

function indicador(id, quem, valor) {
  const el = $(id);
  el.dataset.estado = valor;
  el.querySelector('.ind-texto').textContent =
    valor === 'ok' ? T[quem].ok : `${T[quem].sem_sinal} · ${T.avisoSemSinal[quem]}`;
}

assinar((e) => {
  const faixa = $('faixa-erro');
  faixa.hidden = !e.semConexao;
  faixa.textContent = T.semConexao;
  indicador('ind-mesa', 'mesa', e.equipamentos.mesa);
  indicador('ind-batedor', 'batedor', e.equipamentos.batedor);

  if (e.tela === 'sessao_em_andamento') { location.href = app.dataset.sessao; return; }
  if (e.tela === 'sem_sessao') { location.href = app.dataset.nova; return; }
  $('esp-paciente').textContent = e.sessao.paciente;
});

$('esp-instrucao').textContent = T.espera.instrucao;
$('esp-ajuda').textContent = T.espera.ajuda;
$('b-cancelar-espera').addEventListener('click', () => enviarComando('cancelar_espera'));   // o estado seguinte volta para a Nova sessão
$('b-cancelar-espera').focus();

iniciar();