// batedor_logica.h — pacote UDP do batedor do ESME: lotes de amostras do MPU-6050 (Anexo A.4 do escopo).
//
// Não usa nada do Arduino de propósito: o batedor_esme.ino só chama estas funções, e este mesmo arquivo roda no
// computador para teste. O formato do pacote é o que o site já lê (terapia/protocolo.py: BATEDOR_CABECALHO e BATEDOR_AMOSTRA):
//
//   cabeçalho, 4 bytes     '<HBB'          pkt (contador de pacotes), n (amostras neste pacote, até 8), passo (= 4)
//   cada amostra, 20 bytes '<IIhhhhhh'     seq, t_us, ax, ay, az, gx, gy, gz     (valores brutos do sensor)
//
// Regra: o sensor é lido 100 vezes por segundo. A cada 4 amostras NOVAS sai um pacote com as 8 amostras mais recentes.
// Assim cada amostra viaja em dois pacotes seguidos: se um se perde, o próximo traz as amostras dele de novo.
// Um pacote cheio tem 4 + 8 x 20 = 164 bytes. No começo, enquanto há menos de 8 amostras, n é menor.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define BATEDOR_LOTE_MAX         8       // amostras por pacote (as mais recentes)
#define BATEDOR_PASSO            4       // amostras novas entre um pacote e o seguinte
#define BATEDOR_CABECALHO_BYTES  4
#define BATEDOR_AMOSTRA_BYTES    20
#define BATEDOR_PACOTE_MAX       (BATEDOR_CABECALHO_BYTES + BATEDOR_LOTE_MAX * BATEDOR_AMOSTRA_BYTES)

struct BatedorAmostra {
  uint32_t seq;        // número da amostra (começa em 0 quando o batedor liga)
  uint32_t t_us;       // relógio do batedor (micros()), no instante da leitura
  int16_t  a[3];       // ax, ay, az
  int16_t  g[3];       // gx, gy, gz
};

struct BatedorLote {
  uint32_t proxima_seq;
  uint16_t pkt;                              // contador de pacotes montados
  uint8_t  n;                                // amostras guardadas (0 a 8); a mais antiga fica em [0]
  uint8_t  novas;                            // amostras novas desde o último pacote
  BatedorAmostra amostras[BATEDOR_LOTE_MAX];
};

inline void batedorIniciar(BatedorLote& b) { memset(&b, 0, sizeof(b)); }

// Depois de uma falha do sensor: esquece as amostras velhas (a numeração e o contador de pacotes continuam).
inline void batedorEsquecerLote(BatedorLote& b) { b.n = 0; b.novas = 0; }

// Guarda uma amostra. Devolve true quando está na hora de mandar um pacote (a cada 4 amostras novas).
inline bool batedorAdicionar(BatedorLote& b, uint32_t t_us, const int16_t a[3], const int16_t g[3]) {
  if (b.n >= BATEDOR_LOTE_MAX) {                                 // cheio: esquece a mais antiga
    memmove(&b.amostras[0], &b.amostras[1], (BATEDOR_LOTE_MAX - 1) * sizeof(BatedorAmostra));
    b.n = BATEDOR_LOTE_MAX - 1;
  }
  BatedorAmostra& s = b.amostras[b.n++];
  s.seq = b.proxima_seq++;
  s.t_us = t_us;
  for (int i = 0; i < 3; i++) { s.a[i] = a[i]; s.g[i] = g[i]; }
  if (++b.novas >= BATEDOR_PASSO) { b.novas = 0; return true; }
  return false;
}

inline void batedorPut16(uint8_t* p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
inline void batedorPut32(uint8_t* p, uint32_t v) {
  p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

// Monta o pacote em `saida` (pelo menos BATEDOR_PACOTE_MAX bytes) e devolve o tamanho. As amostras vão da mais
// antiga para a mais nova (o site usa a última como âncora de horário).
inline size_t batedorMontarPacote(BatedorLote& b, uint8_t* saida) {
  batedorPut16(saida, b.pkt++);
  saida[2] = b.n;
  saida[3] = BATEDOR_PASSO;
  uint8_t* p = saida + BATEDOR_CABECALHO_BYTES;
  for (uint8_t i = 0; i < b.n; i++, p += BATEDOR_AMOSTRA_BYTES) {
    const BatedorAmostra& s = b.amostras[i];
    batedorPut32(p, s.seq);
    batedorPut32(p + 4, s.t_us);
    for (int k = 0; k < 3; k++) {
      batedorPut16(p + 8 + 2 * k, (uint16_t)s.a[k]);
      batedorPut16(p + 14 + 2 * k, (uint16_t)s.g[k]);
    }
  }
  return BATEDOR_CABECALHO_BYTES + (size_t)b.n * BATEDOR_AMOSTRA_BYTES;
}