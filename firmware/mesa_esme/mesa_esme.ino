// mesa_esme.ino — mesa do ESME (ESP32): lê as 9 bobinas, mostra os pontos, toca as notas e
// manda o estado da mesa ao notebook por Wi-Fi (UDP 4212, a cada 100 ms).
//
// Base: o código da mesa de 18/10 (bobinas, LEDs, display TM1637 e módulo MP3), mantido como estava.
// Tudo que é novo está marcado com // [ESME]. Fica na MESMA pasta de esme_config.h e mesa_logica.h.
//
// Como a mesa funciona:
//   - Liga TRAVADA. Segurar "nova sessão" por 3 s destrava (o notebook percebe e abre a sessão).
//   - "Nova tentativa" (aperto curto) arma a mesa; o disco cruzando as bobinas conta pontos.
//   - A tentativa acaba no gol ou 3 s depois de o disco parar de avançar. A mesa só volta a contar quando
//     o terapeuta apertar "nova tentativa" de novo.
//   - As regras estão em mesa_logica.h (testadas no computador). Aqui ficam só o hardware e o Wi-Fi.
//
// Dois "núcleos" de trabalho [ESME]: o loop() lê as bobinas sem nunca esperar pelo Wi-Fi; uma tarefa à parte
// (tarefaRede, no outro núcleo do ESP32) monta e manda os pacotes. Assim um atraso da rede não faz perder passagem do disco.
#include <Arduino.h>
#if __has_include(<esp_random.h>)
  #include <esp_random.h>
#endif
#include <esp_system.h>

#define ESME_TIPO         "MESA"      // [ESME]
#define ESME_VERSAO       "1.0"       // [ESME] versão do protocolo de gravação do Wi-Fi (não mude)
#define ESME_PORTA_DADOS  4212        // [ESME]
#include "esme_config.h"              // [ESME] Wi-Fi, gravação da rede pela USB e aviso do IP do notebook
#include "mesa_logica.h"              // [ESME] estados, eventos e pacote

// ===== BOBINAS E MULTIPLEXADOR =====
const int PINO_LEITURA = 36;

const int S0 = 18;
const int S1 = 19;
const int S2 = 22;
const int S3 = 5;

// ===== LEDS =====
const int leds[9] = {
  13, 12, 14, 27, 26, 25, 33, 32, 23
};

bool detectado[9] = {false};

// ===== BOTOES ===== [ESME]
// Ligue cada botao entre o pino e o GND (o ESP32 ja puxa o pino para cima por dentro).
// Se os botoes estiverem em outros pinos, e so trocar os dois numeros abaixo.
const int PINO_BOTAO_TENTATIVA = 15;                 // aperto curto = nova tentativa
const int PINO_BOTAO_SESSAO    = 2;                  // segurar 3 s = nova sessao
const unsigned long TEMPO_NOVA_SESSAO_MS = 3000;

// ===== DISPLAY TM1637 =====
const int CLK = 21;
const int DIO = 4;

const byte segmentos[10] = {
 0x3F, 0x06, 0x5B, 0x4F, 0x66,
 0x6D, 0x7D, 0x07, 0x7F, 0x6F
};

// ===== PLACA MP3 =====
HardwareSerial mp3(2);

const int RX_MP3 = 16;
const int TX_MP3 = 17;

// ===== CONFIGURACOES =====
const int LIMIAR = 100;
const int PONTOS_POR_BOBINA = 1;

int pontos = 0;

// ===== ESTADO DA MESA (compartilhado com a tarefa do Wi-Fi) ===== [ESME]
MesaLogica mesa;
portMUX_TYPE travaMesa = portMUX_INITIALIZER_UNLOCKED;
#define TRAVAR()  portENTER_CRITICAL(&travaMesa)      // trechos curtos: so mexem nas regras, nunca esperam nada
#define LIBERAR() portEXIT_CRITICAL(&travaMesa)

// ===== COMANDO MP3 =====
void comando(byte cmd, int valor) {
  byte d[10] = {
    0x7E, 0xFF, 0x06, cmd, 0x00,
    (byte)(valor >> 8),
    (byte)(valor & 0xFF),
    0, 0, 0xEF
  };

  int soma = 0;

  for (int i = 1; i <= 6; i++) {
    soma += d[i];
  }

  int cs = -soma;

  d[7] = (cs >> 8) & 0xFF;
  d[8] = cs & 0xFF;

  mp3.write(d, 10);
}

// ===== DISPLAY SEM BIBLIOTECA =====
void inicioDisplay() {
  digitalWrite(CLK, HIGH);
  digitalWrite(DIO, HIGH);
  delayMicroseconds(5);
  digitalWrite(DIO, LOW);
}

void fimDisplay() {
  digitalWrite(CLK, LOW);
  digitalWrite(DIO, LOW);
  delayMicroseconds(5);
  digitalWrite(CLK, HIGH);
  delayMicroseconds(5);
  digitalWrite(DIO, HIGH);
}

void enviaByte(byte valor) {
  for (int i = 0; i < 8; i++) {
    digitalWrite(CLK, LOW);
    digitalWrite(DIO, (valor >> i) & 1);
    delayMicroseconds(5);
    digitalWrite(CLK, HIGH);
    delayMicroseconds(5);
  }

  digitalWrite(CLK, LOW);
  pinMode(DIO, INPUT_PULLUP);
  delayMicroseconds(5);
  digitalWrite(CLK, HIGH);
  delayMicroseconds(5);
  digitalWrite(CLK, LOW);
  pinMode(DIO, OUTPUT);
}

void mostrarPontos(int valor) {
  valor = constrain(valor, 0, 9999);

  inicioDisplay();
  enviaByte(0x40);
  fimDisplay();

  inicioDisplay();
  enviaByte(0xC0);

  for (int i = 0; i < 4; i++) {
    int digito = valor % 10;
    valor /= 10;
    enviaByte(segmentos[digito]);
  }

  fimDisplay();

  inicioDisplay();
  enviaByte(0x8F);
  fimDisplay();
}

// ===== SELECIONAR BOBINA =====
void selecionarBobina(int canal) {
  digitalWrite(S0, bitRead(canal, 0));
  digitalWrite(S1, bitRead(canal, 1));
  digitalWrite(S2, bitRead(canal, 2));
  digitalWrite(S3, bitRead(canal, 3));
}

// ===== PLACAR ZERADO ===== [ESME]
// Nova tentativa ou nova sessao: apaga os LEDs, esquece as bobinas ja cruzadas e volta o placar a zero.
void zerarPlacar() {
  for (int i = 0; i < 9; i++) {
    detectado[i] = false;
    digitalWrite(leds[i], LOW);
  }
  pontos = 0;
  mostrarPontos(0);
}

// ===== BOTOES ===== [ESME]
// Filtra a "tremida" do contato: so muda de estado depois de 30 ms estavel.
struct BotaoFiltrado {
  int pino;
  bool apertado;          // estado ja filtrado
  bool bruto;
  unsigned long desde;
  explicit BotaoFiltrado(int p) : pino(p), apertado(false), bruto(false), desde(0) {}
  void atualizar() {
    bool agoraBruto = (digitalRead(pino) == LOW);
    unsigned long agora = millis();
    if (agoraBruto != bruto) { bruto = agoraBruto; desde = agora; }
    if (bruto != apertado && agora - desde >= 30) apertado = bruto;
  }
};

BotaoFiltrado botaoTentativa(PINO_BOTAO_TENTATIVA);
BotaoFiltrado botaoSessao(PINO_BOTAO_SESSAO);

void novaTentativa() {
  TRAVAR();
  bool aceitou = mesaNovaTentativa(mesa, micros());
  LIBERAR();
  if (aceitou) zerarPlacar();
  else Serial.println("Mesa travada: segure 'nova sessao' por 3 s");
}

void novaSessao() {
  TRAVAR();
  mesaNovaSessao(mesa, micros());
  LIBERAR();
  zerarPlacar();
}

void lerBotoes() {
  static bool tentativaAntes = false;
  static bool contandoSessao = false, sessaoDisparou = false;
  static unsigned long sessaoDesde = 0;

  botaoTentativa.atualizar();                           // aperto curto: age ao apertar
  if (botaoTentativa.apertado && !tentativaAntes) novaTentativa();
  tentativaAntes = botaoTentativa.apertado;

  botaoSessao.atualizar();                              // segurar 3 s: age quando completa os 3 s (uma vez por aperto)
  if (!botaoSessao.apertado) {
    contandoSessao = false;
    sessaoDisparou = false;
  } else {
    if (!contandoSessao) { contandoSessao = true; sessaoDesde = millis(); }
    if (!sessaoDisparou && millis() - sessaoDesde >= TEMPO_NOVA_SESSAO_MS) {
      sessaoDisparou = true;
      novaSessao();
    }
  }
}

const char* nomeEstado(MesaEstado e) {
  switch (e) {
    case M_TRAVADA:       return "TRAVADA";
    case M_PRONTA:        return "PRONTA";
    case M_ARMADA:        return "ARMADA (aguardando o disco)";
    case M_EM_TENTATIVA:  return "EM TENTATIVA";
    default:              return "FIM";
  }
}

// ===== WI-FI NO OUTRO NUCLEO ===== [ESME]
// Tudo que fala com a rede fica aqui (inclusive o esmeServico: USB, Wi-Fi e aviso do IP).
// A cada 100 ms manda o estado inteiro da mesa e os eventos dos ultimos 2 s.
void tarefaRede(void*) {
  uint8_t pacote[MESA_PACOTE_MAX];
  bool tinhaWifi = false;
  unsigned long proximo = millis();

  for (;;) {
    esmeServico();

    bool temWifi = esmeConectado();
    if (temWifi && !tinhaWifi) WiFi.setSleep(false);    // sem economia de energia do Wi-Fi: menos atraso e menos variacao
    tinhaWifi = temWifi;

    unsigned long agora = millis();
    if ((long)(agora - proximo) >= 0) {
      proximo += 100;
      if ((long)(agora - proximo) >= 0) proximo = agora + 100;     // atrasou muito: nao tenta recuperar os pacotes

      TRAVAR();
      size_t n = mesaMontarPacote(mesa, micros(), pacote);
      LIBERAR();
      esmeEnviar(pacote, n);                            // sem Wi-Fi ou sem destino ele so devolve false
    }
    delay(2);
  }
}

// ===== INICIALIZACAO =====
void setup() {
  Serial.begin(115200);

  esmeIniciar();                                        // [ESME] le o Wi-Fi guardado na placa e comeca a conectar
  mesaIniciar(mesa, (uint16_t)(esp_random() & 0xFFFF)); // [ESME] a mesa liga travada

  analogReadResolution(12);

  pinMode(S0, OUTPUT);
  pinMode(S1, OUTPUT);
  pinMode(S2, OUTPUT);
  pinMode(S3, OUTPUT);

  for (int i = 0; i < 9; i++) {
    pinMode(leds[i], OUTPUT);
    digitalWrite(leds[i], LOW);
  }

  pinMode(PINO_BOTAO_TENTATIVA, INPUT_PULLUP);          // [ESME]
  pinMode(PINO_BOTAO_SESSAO, INPUT_PULLUP);             // [ESME]

  pinMode(CLK, OUTPUT);
  pinMode(DIO, OUTPUT);

  digitalWrite(CLK, HIGH);
  digitalWrite(DIO, HIGH);

  mostrarPontos(0);

  // [ESME] a tarefa do Wi-Fi comeca ja, antes da musica: o site ve a mesa "Conectada" (travada) sem esperar os 25 s
  xTaskCreatePinnedToCore(tarefaRede, "rede", 10240, nullptr, 1, nullptr, 0);

  mp3.begin(
    9600, SERIAL_8N1,
    RX_MP3, TX_MP3
  );

  delay(2000);

  // Volume
  comando(0x06, 15);
  delay(1000);

  // Musica 11 na abertura
  comando(0x03, 11);

  Serial.println("Musica de abertura");

  delay(25000);

  // Parar musica
  comando(0x16, 0);
  delay(300);
  comando(0x06, 25); // volta som mais alto para toque das bobinas
  delay(300);

  Serial.println("Sistema pronto! Mesa TRAVADA: segure 'nova sessao' por 3 s.");
}

// ===== PROGRAMA PRINCIPAL =====
void loop() {
  lerBotoes();                                          // [ESME]

  TRAVAR();                                             // [ESME] passaram 3 s sem o disco avancar? a tentativa acaba
  mesaTempo(mesa, micros());
  MesaEstado estado = mesa.estado;
  uint8_t motivoFim = mesa.motivo_fim;
  LIBERAR();

  static MesaEstado estadoVisto = M_TRAVADA;            // [ESME] avisa na serial cada mudanca de estado
  if (estado != estadoVisto) {
    estadoVisto = estado;
    Serial.print("Estado: ");
    Serial.print(nomeEstado(estado));
    if (estado == M_FIM) Serial.print(motivoFim == MOT_GOL ? " - gol" : " - parou");
    Serial.println();
  }

  if (estado != M_ARMADA && estado != M_EM_TENTATIVA) { // [ESME] travada, pronta ou fim: nao le as bobinas
    delay(1);
    return;
  }

  for (int i = 0; i < 9; i++) {

    selecionarBobina(i);

    delayMicroseconds(100);

    int leitura = analogRead(PINO_LEITURA);
    uint32_t instante = micros();                       // [ESME] hora da leitura

    // Detecta somente a primeira
    // passagem em cada bobina
    if (leitura > LIMIAR && !detectado[i]) {

      TRAVAR();                                         // [ESME] a mesa avisa o notebook (bobina i+1; a 9a e o gol)
      bool valeu = mesaCruzou(mesa, i + 1, instante);
      LIBERAR();
      if (!valeu) continue;                             // [ESME] fora da tentativa: nao conta

      detectado[i] = true;

      // Acende LED correspondente
      digitalWrite(leds[i], HIGH);

      // Soma pontos
      pontos += PONTOS_POR_BOBINA;

      // Atualiza display
      mostrarPontos(pontos);

      // Toca nota correspondente
      comando(0x03, i + 1);

      Serial.print("Bobina: ");
      Serial.print(i + 1);

      Serial.print(" Pontos: ");
      Serial.println(pontos);
    }
  }
}
