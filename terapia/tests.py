/* textos.js — TODOS os textos que mudam na tela ficam aqui, em português.
   O programa (back) só envia códigos ("baixa", "sem_dados_batedor"); a tela escolhe a frase. */

export const T = {
  mesa:    { ok: 'Conectada', sem_sinal: 'Sem sinal' },
  batedor: { ok: 'Conectado', sem_sinal: 'Sem sinal' },
  // frase curta ao lado de "Sem sinal" (seção 7.1 do escopo do Sandro)
  avisoSemSinal: {
    mesa: 'nenhuma tentativa será registrada',
    batedor: 'a fluidez não será registrada',
  },
  semConexao: 'Sem conexão com o programa. Tentando reconectar…',

  fluidez: { alta: 'alta', media: 'média', baixa: 'baixa', indisponivel: 'indisponível' },
  motivoFluidez: {
    sem_dados_batedor: 'sem dados do batedor',
    sem_repouso: 'sem repouso de referência',
    nao_calculada: 'cálculo ainda não disponível',
  },

  resultado: { gol: 'Gol', parou: 'Parou', interrompida: 'Interrompida' },
  motivoTentativa: {
    nova_tentativa: 'nova tentativa apertada antes do fim',
    nova_sessao: 'a mesa foi zerada durante a tentativa',
    mesa_reiniciou: 'a mesa reiniciou durante a tentativa',
  },

  alcanceNenhum: 'nenhum',
  anulada: 'anulada',
  tentativa: {
    aguardando_disco: 'Aguardando o disco…',
    calculando: 'Calculando fluidez…',
    emAndamento: (alcance) => `Em andamento, alcance até agora: ${alcance}`,
  },
  semTentativas: 'Nenhuma tentativa ainda. Aperte nova tentativa na mesa e peça ao paciente que bata no disco.',

  acoes: { detalhes: 'Detalhes', anular: 'Anular', restaurar: 'Restaurar' },

  detalhe: {
    calculando: 'Calculando…',
    legenda: 'Um pico só: movimento fluido. Vários picos: movimento entrecortado.',
    semCurva: {
      sem_dados_batedor: 'Sem dados do batedor nesta tentativa.',
      sem_repouso: 'Sem repouso de referência para calcular a velocidade.',
    },
  },

  novaSessao: {
    erroNome: 'Digite o nome do paciente.',
    erroData: 'Digite uma data válida no formato dd/mm/aaaa.',
  },

  espera: {
    instrucao: 'Aperte e segure o botão "nova sessão" da mesa até o placar mostrar -- --.',
    ajuda: 'Se esta tela não avançar, confira se a Mesa está "Conectada" no topo e segure o botão de novo.',
  },

  // códigos de erro que o programa devolve -> frase (código sem frase cai em "Algo deu errado")
  erros: {
    paciente_vazio: 'Digite o nome do paciente.',
    paciente_longo: 'O nome do paciente é longo demais (máximo de 150 letras).',
    data_invalida: 'Digite uma data válida no formato dd/mm/aaaa.',
    sessao_aberta: 'Há uma sessão aberta. Encerre-a antes de começar outra.',
    sem_perfil: 'Esta conta não é de fisioterapeuta, então não pode abrir sessões.',
    sem_permissao: 'Você não tem permissão para isso. Entre de novo na sua conta.',
    sem_conexao: 'Sem conexão com o programa.',
  },
  erroGenerico: (codigo) => `Algo deu errado (código ${codigo}).`,
};