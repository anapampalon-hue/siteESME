// batedor_esme.ino — batedor sem fio do ESME (ESP8266 + sensor MPU-6050 / módulo GY-521).
// Lê o acelerômetro e o giroscópio 100 vezes por segundo e manda as amostras ao notebook por Wi-Fi (UDP 4210).
// Fica na MESMA pasta de esme_config.h e batedor_logica.h.
//
// Como funciona:
//   - O sensor trabalha em ±16 g e ±1000 °/s, a 100 amostras por segundo (como o site espera).
//   - A cada 4 amostras novas sai um pacote com as 8 mais recentes (Anexo A.4 do escopo): cada amostra viaja em dois
//     pacotes seguidos, então um pacote perdido não faz perder amostra. O formato está em batedor_logica.h.
//   - O batedor manda pacotes o tempo todo (também fora da sessão): é isso que acende a bolinha "Batedor" no site.
//     Se o sensor não responde, o batedor NÃO manda nada, e o site mostra "Sem sinal" (o certo: não há dado).
//   - O Wi-Fi é gravado pelo cabo USB (página Configurações do site). Depois disso a placa conecta sozinha.
//   - Na serial só saem as respostas do protocolo USB (esme_config.h). Nada de mensagens soltas.
//
// LED da placa:   piscadas rápidas = sensor não responde  ·  piscada lenta = sem Wi-Fi  ·  um lampejo a cada 2 s = tudo certo.
//
// Ligação do sensor (conferir com a sua placa; trocar as constantes abaixo se for diferente):
//   VCC -> 3V3 · GND -> GND · SDA -> D2 (GPIO 4) · SCL -> D1 (GPIO 5) · AD0 solto ou no GND (endereço 0x68; 0x69 também é aceito).
#include <Arduino.h>
#include <Wire.h>

#define ESME_TIPO         "BATEDOR"   // [ESME]
#define ESME_VERSAO       "1.0"       // [ESME] versão do protocolo de gravação do Wi-Fi (não mude)
#define ESME_PORTA_DADOS  4210        // [ESME]
#include "esme_config.h"              // [ESME] Wi-Fi, gravação da rede pela USB e aviso do IP do notebook
#include "batedor_logica.h"           // [ESME] lote de amostras e pacote

#ifndef BATEDOR_DEPURAR
#define BATEDOR_DEPURAR 1             // 1 = escreve um resumo por segundo na serial (só para achar defeito na bancada). Deixe 0 no uso normal.
#endif

// ===== SENSOR (I2C) =====
const int PINO_SDA = 4;               // D2
const int PINO_SCL = 5;               // D1
const uint32_t VELOCIDADE_I2C = 400000;   // se o LED piscar rápido de vez em quando, tente 100000
const uint8_t ENDERECO_1 = 0x68;      // AD0 no GND (ou solto)
const uint8_t ENDERECO_2 = 0x69;      // AD0 no 3V3

const uint32_t PERIODO_US = 10000;    // 100 amostras por segundo
const uint8_t  FALHAS_PARA_REINICIAR = 20;   // leituras seguidas com erro (0,2 s) antes de reiniciar o sensor
const unsigned long INTERVALO_TENTATIVA_MS = 1000;   // sensor ausente: tenta de novo a cada 1 s
const unsigned long PRIMEIRA_TENTATIVA_MS  = 300;    // logo depois de uma falha no meio do uso: a 1ª nova tentativa vem em 0,3 s

// registradores do MPU-6050
const uint8_t REG_SMPLRT_DIV   = 0x19;
const uint8_t REG_CONFIG       = 0x1A;
const uint8_t REG_GYRO_CONFIG  = 0x1B;
const uint8_t REG_ACCEL_CONFIG = 0x1C;
const uint8_t REG_DADOS        = 0x3B;   // ax ay az temperatura gx gy gz (14 bytes, o byte alto vem primeiro)
const uint8_t REG_PWR_MGMT_1   = 0x6B;

BatedorLote lote;
uint8_t  mpuEndereco = 0;
bool     sensorOk = false;
uint8_t  falhasSeguidas = 0;
uint32_t proximaLeitura = 0;
unsigned long ultimaTentativaSensor = 0;
bool     estavaConectado = false;

// diagnóstico (só aparece na serial com BATEDOR_DEPURAR = 1)
uint8_t  mpuMotivo = 0;               // por que o sensor não iniciou: 1 sem resposta · 2 reiniciar · 3 acordar · 4 configurar · 5 faixa de ±16 g não conferiu
uint8_t  mpuFaixaLida = 0;            // o que o registrador de faixa devolveu (esperado 0x18)
uint32_t enviados = 0, enviosFalhos = 0, leiturasFalhas = 0, reinicios = 0;

// ---------------------------------------------------------------- I2C ----------
static bool mpuEscrever(uint8_t reg, uint8_t valor) {
  Wire.beginTransmission(mpuEndereco);
  Wire.write(reg);
  Wire.write(valor);
  return Wire.endTransmission() == 0;
}

static bool mpuLer(uint8_t reg, uint8_t* destino, uint8_t n) {
  Wire.beginTransmission(mpuEndereco);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(mpuEndereco, n) != n) return false;
  for (uint8_t i = 0; i < n; i++) {
    int c = Wire.read();
    if (c < 0) return false;
    destino[i] = (uint8_t)c;
  }
  return true;
}

// Acorda e configura o sensor. Devolve false se ele não responde ou não aceitou a configuração.
static bool mpuIniciar() {
  mpuMotivo = 0;
  mpuEndereco = 0;
  const uint8_t candidatos[2] = { ENDERECO_1, ENDERECO_2 };
  for (uint8_t i = 0; i < 2 && !mpuEndereco; i++) {
    Wire.beginTransmission(candidatos[i]);
    if (Wire.endTransmission() == 0) mpuEndereco = candidatos[i];
  }
  if (!mpuEndereco) { mpuMotivo = 1; return false; }

  if (!mpuEscrever(REG_PWR_MGMT_1, 0x80)) { mpuMotivo = 2; return false; }     // reinicia o chip
  delay(100);
  if (!mpuEscrever(REG_PWR_MGMT_1, 0x01)) { mpuMotivo = 3; return false; }     // acorda; relógio = giroscópio X
  delay(10);
  bool ok = true;
  ok &= mpuEscrever(REG_SMPLRT_DIV, 9);                     // 1 kHz / (1 + 9) = 100 amostras por segundo
  ok &= mpuEscrever(REG_CONFIG, 0x01);                      // filtro de 184 Hz (deixa passar o impacto)
  ok &= mpuEscrever(REG_GYRO_CONFIG, 0x10);                 // ±1000 °/s
  ok &= mpuEscrever(REG_ACCEL_CONFIG, 0x18);                // ±16 g (o site conta 2048 por g)
  if (!ok) { mpuMotivo = 4; return false; }

  uint8_t faixa = 0;                                        // conferência: a faixa de ±16 g ficou mesmo gravada?
  bool leu = mpuLer(REG_ACCEL_CONFIG, &faixa, 1);
  mpuFaixaLida = faixa;
  if (!leu || faixa != 0x18) { mpuMotivo = 5; return false; }
  return true;
}

static inline int16_t lerInt16(const uint8_t* p) { return (int16_t)(((uint16_t)p[0] << 8) | p[1]); }

// Lê uma amostra. Devolve false se a leitura falhou.
static bool mpuAmostra(int16_t a[3], int16_t g[3]) {
  uint8_t b[14];
  if (!mpuLer(REG_DADOS, b, 14)) return false;
  a[0] = lerInt16(b + 0);  a[1] = lerInt16(b + 2);  a[2] = lerInt16(b + 4);       // b[6..7] = temperatura (não usada)
  g[0] = lerInt16(b + 8);  g[1] = lerInt16(b + 10); g[2] = lerInt16(b + 12);
  return true;
}

// ---------------------------------------------------------------- LED ----------
static void ledAtualizar() {
  unsigned long t = millis();
  bool aceso;
  if (!sensorOk)              aceso = (t / 100) % 2 == 0;       // rápido: sensor
  else if (!esmePodeEnviar()) aceso = (t / 500) % 2 == 0;       // lento: Wi-Fi
  else                        aceso = (t % 2000) < 40;          // lampejo: tudo certo
  digitalWrite(LED_BUILTIN, aceso ? LOW : HIGH);                // o LED da placa acende com LOW
}

#if BATEDOR_DEPURAR
// Uma linha por segundo:  wifi = 3 conectado · 1 rede não encontrada · 6 senha errada · 7 caiu · 0 procurando.
static void resumoSerial() {
  static unsigned long ultimo = 0;
  if (millis() - ultimo < 1000) return;
  ultimo = millis();
  Serial.print("DEP sensor=");          Serial.print(sensorOk ? "ok" : "FALHA");
  Serial.print(" motivo=");             Serial.print(mpuMotivo);
  Serial.print(" faixa=0x");            Serial.print(mpuFaixaLida, HEX);
  Serial.print(" wifi=");               Serial.print((int)WiFi.status());
  Serial.print(" destino=");            Serial.print(esmePodeEnviar() ? "ok" : "NAO");
  Serial.print(" rssi=");               Serial.print(WiFi.RSSI());
  Serial.print(" ip=");                 Serial.print(WiFi.localIP());
  Serial.print(" enviados=");           Serial.print(enviados);
  Serial.print(" falhas_envio=");       Serial.print(enviosFalhos);
  Serial.print(" falhas_leitura=");     Serial.print(leiturasFalhas);
  Serial.print(" reinicios=");          Serial.println(reinicios);
}
#endif

// ---------------------------------------------------------------- programa ----------
static void semEconomiaDeEnergia() { WiFi.setSleepMode(WIFI_NONE_SLEEP); }    // o modo de economia atrasa os pacotes

static void reiniciarSensor() {
  reinicios++;
  Wire.begin(PINO_SDA, PINO_SCL);                          // solta o barramento se ele travou
  Wire.setClock(VELOCIDADE_I2C);
  Wire.setClockStretchLimit(2000);                         // clones do MPU-6050 podem demorar a responder
  sensorOk = mpuIniciar();
  falhasSeguidas = 0;
  batedorEsquecerLote(lote);
  proximaLeitura = micros() + PERIODO_US;
  ultimaTentativaSensor = millis();
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);
  batedorIniciar(lote);
  esmeIniciar();
  semEconomiaDeEnergia();
  reiniciarSensor();
}

void loop() {
  esmeServico();                                           // USB (gravação do Wi-Fi), reconexão e aviso do IP
#if BATEDOR_DEPURAR
  resumoSerial();
#endif

  bool conectado = esmeConectado();
  if (conectado && !estavaConectado) semEconomiaDeEnergia();   // o Wi-Fi acabou de (re)conectar
  estavaConectado = conectado;

  if (!sensorOk) {                                         // sensor ausente: tenta de novo a cada 1 s, sem mandar nada
    if (millis() - ultimaTentativaSensor >= INTERVALO_TENTATIVA_MS) reiniciarSensor();
    ledAtualizar();
    yield();
    return;
  }

  uint32_t agora = micros();
  int32_t atraso = (int32_t)(agora - proximaLeitura);
  if (atraso >= 0) {
    if (atraso > (int32_t)PERIODO_US) proximaLeitura = agora;   // perdeu mais de um período: recomeça, sem rajada
    proximaLeitura += PERIODO_US;

    int16_t a[3], g[3];
    if (mpuAmostra(a, g)) {
      falhasSeguidas = 0;
      if (batedorAdicionar(lote, agora, a, g)) {
        uint8_t pacote[BATEDOR_PACOTE_MAX];
        size_t tamanho = batedorMontarPacote(lote, pacote);
        if (esmeEnviar(pacote, tamanho)) enviados++;       // sem Wi-Fi devolve false; as amostras seguintes continuam
        else enviosFalhos++;
      }
    } else {
      leiturasFalhas++;
      if (++falhasSeguidas >= FALHAS_PARA_REINICIAR) {
        sensorOk = false;                                  // para de mandar: o site mostra "Sem sinal"
        ultimaTentativaSensor = millis() - (INTERVALO_TENTATIVA_MS - PRIMEIRA_TENTATIVA_MS);
      }
    }
  }

  ledAtualizar();
  yield();
}
