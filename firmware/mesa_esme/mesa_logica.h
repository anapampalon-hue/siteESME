// mesa_logica.h — regras da mesa do ESME: máquina de estados, eventos e montagem do pacote UDP.
//
// Não usa nada do Arduino de propósito: o mesa_esme.ino só chama estas funções, e este mesmo arquivo roda no
// computador para teste. O formato do pacote é o que o site já lê (terapia/protocolo.py: MESA_CABECALHO e MESA_EVENTO):
//
//   cabeçalho, 14 bytes   '<BHHHBBIB'   estado, boot_id, contador_sessao, contador_tentativas,
//                                       bobina_max, motivo_fim, t_us, n_eventos
//   cada evento, 10 bytes '<IBBI'       ev_id, tipo, valor, t_us          (até 16 eventos, os dos últimos 2 s)
//
//   estado : 0 travada · 1 aguardando (pronta ou armada) · 2 em tentativa · 3 fim
//   evento : tipo 1 iniciada · 2 bobina (valor = 1 a 8) · 3 gol · 4 fim (valor = motivo)
//   motivo : 1 gol · 2 parou · 3 nova tentativa · 4 nova sessão
//
// Regras (as aprovadas pelo grupo):
//   - A mesa liga TRAVADA. Segurar "nova sessão" por 3 s destrava e soma 1 em contador_sessao (esse aperto não tem evento).
//   - "Nova tentativa" (aperto curto) arma a mesa. Travada, ele é ignorado.
//   - Só a PRIMEIRA passagem de cada bobina conta. Bobina pulada é aceita; o alcance é a mais alta cruzada.
//   - A tentativa acaba no gol ou quando passam 3 s sem o disco cruzar uma bobina MAIS ALTA que a atual.
//     Armada (nenhuma bobina cruzada ainda) não tem prazo.
//   - Apertar "nova tentativa" ou "nova sessão" com uma tentativa em curso a encerra com um evento de fim (motivo 3 ou 4).
//   - O pacote leva o estado inteiro e os eventos dos últimos 2 s; assim um pacote perdido não perde nada.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define MESA_MAX_ENVIADOS     16          // eventos por pacote
#define MESA_MAX_GUARDADOS    32          // eventos lembrados na mesa
#define MESA_JANELA_US        2000000UL   // os eventos se repetem nos pacotes por 2 s
#define MESA_PARADA_US        300000UL   // 3 s sem avançar = "parou"
#define MESA_CABECALHO_BYTES  14
#define MESA_EVENTO_BYTES     10
#define MESA_PACOTE_MAX       (MESA_CABECALHO_BYTES + MESA_MAX_ENVIADOS * MESA_EVENTO_BYTES)

enum MesaEstado : uint8_t { M_TRAVADA = 0, M_PRONTA = 1, M_ARMADA = 2, M_EM_TENTATIVA = 3, M_FIM = 4 };

static const uint8_t MESA_EV_INICIO = 1, MESA_EV_BOBINA = 2, MESA_EV_GOL = 3, MESA_EV_FIM = 4;
static const uint8_t MOT_GOL = 1, MOT_PAROU = 2, MOT_NOVA_TENTATIVA = 3, MOT_NOVA_SESSAO = 4;

struct MesaEvento {
  uint32_t ev_id;
  uint8_t  tipo;
  uint8_t  valor;
  uint32_t t_us;
};

struct MesaLogica {
  MesaEstado estado;
  uint16_t boot_id;               // sorteado a cada vez que a mesa liga: o site percebe o reinício
  uint16_t contador_sessao;       // sobe 1 a cada aperto de 3 s em "nova sessão"
  uint16_t contador_tentativas;   // tentativas iniciadas desde o último aperto de 3 s
  uint8_t  bobina_max;            // bobina mais alta cruzada na tentativa (0 a 8; o gol conta 8)
  uint8_t  motivo_fim;            // só no estado fim: 1 gol, 2 parou. Nos outros, 0
  uint16_t cruzadas;              // bit b = 1 se a bobina b (1 a 9) já foi cruzada nesta tentativa
  uint32_t t_avanco_us;           // instante do último avanço (para os 3 s)
  uint32_t ultimo_ev_id;
  uint8_t  n_evs;
  MesaEvento evs[MESA_MAX_GUARDADOS];
};

// ---------------------------------------------------------------- eventos ----------
inline void mesaIniciar(MesaLogica& m, uint16_t boot_id) {
  memset(&m, 0, sizeof(m));
  m.estado = M_TRAVADA;
  m.boot_id = boot_id;
}

inline bool mesaEmCurso(const MesaLogica& m) {
  return m.estado == M_ARMADA || m.estado == M_EM_TENTATIVA;
}

inline void mesaGerarEvento(MesaLogica& m, uint8_t tipo, uint8_t valor, uint32_t t_us) {
  if (m.n_evs >= MESA_MAX_GUARDADOS) {                          // cheio: esquece o mais antigo
    memmove(&m.evs[0], &m.evs[1], (MESA_MAX_GUARDADOS - 1) * sizeof(MesaEvento));
    m.n_evs = MESA_MAX_GUARDADOS - 1;
  }
  m.ultimo_ev_id++;
  MesaEvento& e = m.evs[m.n_evs++];
  e.ev_id = m.ultimo_ev_id;
  e.tipo = tipo;
  e.valor = valor;
  e.t_us = t_us;
}

// ---------------------------------------------------------------- botões ----------
// "Nova sessão" já com os 3 s completos (chame uma vez por aperto).
inline void mesaNovaSessao(MesaLogica& m, uint32_t agora_us) {
  if (mesaEmCurso(m)) mesaGerarEvento(m, MESA_EV_FIM, MOT_NOVA_SESSAO, agora_us);
  m.estado = M_PRONTA;
  m.contador_sessao++;
  m.contador_tentativas = 0;
  m.bobina_max = 0;
  m.motivo_fim = 0;
  m.cruzadas = 0;
}

// "Nova tentativa" (aperto curto). Devolve false se a mesa está travada (aperto ignorado).
inline bool mesaNovaTentativa(MesaLogica& m, uint32_t agora_us) {
  if (m.estado == M_TRAVADA) return false;
  if (mesaEmCurso(m)) mesaGerarEvento(m, MESA_EV_FIM, MOT_NOVA_TENTATIVA, agora_us);
  m.estado = M_ARMADA;
  m.contador_tentativas++;
  m.bobina_max = 0;
  m.motivo_fim = 0;
  m.cruzadas = 0;
  mesaGerarEvento(m, MESA_EV_INICIO, 0, agora_us);
  return true;
}

// ---------------------------------------------------------------- bobinas ----------
// O disco cruzou a bobina b (1 a 8 = checkpoints, 9 = gol). Devolve true se a passagem valeu
// (mesa armada ou em tentativa, e primeira vez que essa bobina é cruzada nesta tentativa).
inline bool mesaCruzou(MesaLogica& m, uint8_t b, uint32_t agora_us) {
  if (!mesaEmCurso(m) || b < 1 || b > 9) return false;
  if (m.cruzadas & (1u << b)) return false;
  m.cruzadas |= (uint16_t)(1u << b);

  if (b == 9) {                                                  // gol: o gol e o fim levam o mesmo instante
    m.bobina_max = 8;
    mesaGerarEvento(m, MESA_EV_GOL, 0, agora_us);
    mesaGerarEvento(m, MESA_EV_FIM, MOT_GOL, agora_us);
    m.estado = M_FIM;
    m.motivo_fim = MOT_GOL;
    return true;
  }

  mesaGerarEvento(m, MESA_EV_BOBINA, b, agora_us);
  if (m.estado == M_ARMADA || b > m.bobina_max) m.t_avanco_us = agora_us;   // os 3 s recomeçam só se avançou
  if (b > m.bobina_max) m.bobina_max = b;
  m.estado = M_EM_TENTATIVA;
  return true;
}

// Chame sempre que puder: se passaram 3 s sem avançar, a tentativa acaba ("parou").
inline void mesaTempo(MesaLogica& m, uint32_t agora_us) {
  if (m.estado == M_EM_TENTATIVA && (uint32_t)(agora_us - m.t_avanco_us) >= MESA_PARADA_US) {
    mesaGerarEvento(m, MESA_EV_FIM, MOT_PAROU, m.t_avanco_us + MESA_PARADA_US);   // hora em que os 3 s se completaram
    m.estado = M_FIM;
    m.motivo_fim = MOT_PAROU;
  }
}

// ---------------------------------------------------------------- pacote ----------
inline uint8_t mesaEstadoNoPacote(MesaEstado e) {
  switch (e) {
    case M_TRAVADA:       return 0;
    case M_PRONTA:
    case M_ARMADA:        return 1;       // "aguardando"
    case M_EM_TENTATIVA:  return 2;
    default:              return 3;       // fim
  }
}

inline void mesaPut16(uint8_t* p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
inline void mesaPut32(uint8_t* p, uint32_t v) {
  p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

// Monta o pacote de agora (estado inteiro + eventos dos últimos 2 s) em `saida` (pelo menos MESA_PACOTE_MAX bytes).
// Devolve o tamanho. Também esquece os eventos com mais de 2 s; chame a cada 100 ms, mesmo sem Wi-Fi.
inline size_t mesaMontarPacote(MesaLogica& m, uint32_t agora_us, uint8_t* saida) {
  uint8_t mantidos = 0;
  for (uint8_t i = 0; i < m.n_evs; i++) {
    int32_t idade = (int32_t)(agora_us - m.evs[i].t_us);        // negativa = evento "do futuro" (outro núcleo): mantém
    if (idade <= (int32_t)MESA_JANELA_US) m.evs[mantidos++] = m.evs[i];
  }
  m.n_evs = mantidos;

  uint8_t primeiro = (m.n_evs > MESA_MAX_ENVIADOS) ? (uint8_t)(m.n_evs - MESA_MAX_ENVIADOS) : 0;   // só os mais novos
  uint8_t n = (uint8_t)(m.n_evs - primeiro);

  saida[0] = mesaEstadoNoPacote(m.estado);
  mesaPut16(saida + 1, m.boot_id);
  mesaPut16(saida + 3, m.contador_sessao);
  mesaPut16(saida + 5, m.contador_tentativas);
  saida[7] = m.bobina_max;
  saida[8] = m.motivo_fim;
  mesaPut32(saida + 9, agora_us);
  saida[13] = n;

  uint8_t* p = saida + MESA_CABECALHO_BYTES;
  for (uint8_t i = 0; i < n; i++, p += MESA_EVENTO_BYTES) {
    const MesaEvento& e = m.evs[primeiro + i];
    mesaPut32(p, e.ev_id);
    p[4] = e.tipo;
    p[5] = e.valor;
    mesaPut32(p + 6, e.t_us);
  }
  return MESA_CABECALHO_BYTES + (size_t)n * MESA_EVENTO_BYTES;
}
