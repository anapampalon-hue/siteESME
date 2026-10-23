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
  semEstado: 'A tela não conseguiu ler o estado do programa.',

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
  sessao: {
    encerrando: 'Encerrando…',
    encerrar: 'Encerrar sessão',
    fechar: 'Fechar',
    encerrada: 'Sessão encerrada. Você ainda pode anular ou desfazer tentativas.',
    aguardaFim: 'Esperando o disco parar para encerrar…',
    interrompida: 'Esta sessão foi interrompida: o programa foi fechado antes de ela ser encerrada. Confira as tentativas e clique em "Encerrar sessão" para concluí-la.',
    concluindo: 'Encerrando…',
  },

  // comentário da terapeuta (opcional) — o texto é guardado criptografado
  comentario: {
    titulo: 'Comentários da terapeuta',
    opcional: '(opcional)',
    dica: 'Não precisa escrever nada. Evite colocar o nome do paciente: o código já o identifica.',
    placeholder: 'Ex.: paciente cansou na metade; boa amplitude no ombro direito…',
    salvando: 'Salvando…',
    salvo: 'Salvo',
    contador: (n, max) => `${n}/${max}`,
  },
  exportar: { pdf: 'Exportar PDF', csv: 'Baixar CSV' },
  codigo: 'Código',

  historico: {
    colData: 'Data e hora', colPaciente: 'Paciente', colCodigo: 'Código', colFisio: 'Fisioterapeuta',
    colValidas: 'Tentativas válidas', colMelhor: 'Melhor alcance', colStatus: 'Situação', colAcoes: 'Ações',
    status: { concluida: 'Concluída', interrompida: 'Interrompida' },
    comComentario: 'com comentário',
    abrir: 'Abrir', pdf: 'PDF', csv: 'CSV',
    vazio: 'Nenhuma sessão ainda.',
    nadaEncontrado: 'Nenhuma sessão encontrada com esses filtros.',
    dicaCodigos: 'Os pacientes aparecem pelo código (pseudônimo). Marque "Mostrar nomes" para ver os nomes.',
    dicaNomes: 'Os nomes estão visíveis. Desmarque "Mostrar nomes" antes de mostrar a tela a outras pessoas.',
    erroAbrirComSessao: 'Há uma sessão em andamento. Termine-a antes de abrir outra do histórico.',
  },
  resumo: { calculando: 'calculando' },

  // cartão "O que fazer agora" da Sessão (passo a passo; o passo da hora fica destacado)
  guia: {
    pronto: 'Posicione o disco e aperte "nova tentativa" na mesa.',
    aguardandoDisco: 'Peça ao paciente que bata no disco.',
    discoRolando: 'Espere a jogada acabar: o disco precisa parar ou chegar ao gol.',
    encerrada: 'Sessão encerrada. Se quiser, anule tentativas, comente ou exporte; depois clique em Fechar.',
    interrompida: 'Sessão interrompida. Confira as tentativas e clique em "Encerrar sessão" para concluí-la.',
    avisoAmbos: 'Mesa e batedor sem sinal: nada será registrado.',
    avisoMesa: 'Mesa sem sinal: nenhuma tentativa será registrada.',
    avisoBatedor: 'Batedor sem sinal: a fluidez não será registrada.',
  },

  semTentativas: 'Nenhuma tentativa ainda. Aperte nova tentativa na mesa e peça ao paciente que bata no disco.',

  acoes: { detalhes: 'Detalhes', anular: 'Anular', restaurar: 'Desfazer' },   // 'restaurar' é o nome do comando; na tela é "Desfazer"

  detalhe: {
    calculando: 'Calculando o gráfico…',
    carregando: 'Carregando o gráfico…',
    semGrafico: 'Não há gráfico para esta tentativa.',
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
    nao_encontrado: 'Não encontrei essa sessão. Volte ao histórico e tente de novo.',
    comentario_longo: 'O comentário é longo demais (máximo de 2000 letras).',
    sem_conexao: 'Sem conexão com o programa.',
    banco_desatualizado: 'O banco de dados está desatualizado. Pare o site (Ctrl+C) e rode: python manage.py makemigrations e depois python manage.py migrate.',
  },
  erroGenerico: (codigo) => `Algo deu errado (código ${codigo}).`,
};