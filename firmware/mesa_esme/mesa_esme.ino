// mesa_esme.ino — mesa do ESME (ESP32): DISCO VOADOR versão 15 + conexão com o site.
//
// Base: o código "DISCO VOADOR - VERSAO 15" (9 bobinas, 3 LEDs, fita WS2812B, display TM1637 e módulo MP3),
// com o mesmo comportamento: música de abertura de 15 s, espera de estabilização, LIMIAR 70, a fita acende o
// grupo de cada bobina. [ESME] Rev 5 (10/11): o placar mostra os pontos da tabela do conceito (100·k², pela bobina MAIS
// ALTA atingida; gol = 9999) e a nota de cada bobina (faixas 2 a 10) toca NA HORA do cruzamento; no fim da tentativa a mesa
// fica em silêncio. (No v15 e até a rev 4 as notas tocavam DEPOIS da jogada.)
// [ESME] Rev 6 (10/11): FILTRO DE RAJADA. Com a nota tocando na hora, o som do módulo MP3 fazia 3 a 5 bobinas "dispararem"
// quase juntas (~190 ms depois da nota; dados reais do site) e a tentativa acabava em gol falso. Veja "FILTRO DE RAJADA".
// Tudo que é novo está marcado com // [ESME]. Fica na MESMA pasta de esme_config.h e mesa_logica.h.
//
// Como a mesa funciona com o site:
//   - UM botão só (pino 15, o do v15), com dois gestos:
//       aperto CURTO (solto antes de 3 s) = "nova tentativa": arma a mesa. Só vale com a sessão criada, isto é, depois
//                      de uma "nova sessão"; com a mesa travada o aperto curto não faz nada. Age ao SOLTAR, para um
//                      aperto longo nunca armar uma tentativa.
//       SEGURAR 3 s    = "nova sessão": destrava, zera e põe "----" no placar (o site percebe o aperto de 3 s e abre a
//                      sessão). Vale em QUALQUER estado da mesa e age assim que completa os 3 s.
//   - Liga TRAVADA. Um botão que já "nasce" apertado (pino lendo LOW ao ligar: preso, fio no GND, ou segurado durante a
//     música) é ignorado até ser solto uma vez, para a mesa NUNCA se destravar sozinha ao ligar. A serial mostra o
//     nível do pino ("Entradas ao ligar: ...") e avisa se ele estiver preso.
//   - "Nova tentativa" arma a mesa. Ela espera as bobinas estabilizarem
//     (como no v15) e a partir daí o disco cruzando as bobinas conta.
//   - A tentativa acaba no gol ou 3 s depois de o disco parar de avançar (rev 5: sem repetir as notas; a nota de cada
//     bobina já tocou quando o disco a cruzou). A mesa só volta a contar quando o terapeuta apertar "nova tentativa".
//   - As regras estão em mesa_logica.h (testadas no computador). Aqui ficam só o hardware e o Wi-Fi.
//
// Dois "núcleos" de trabalho [ESME]: o loop() lê as bobinas sem nunca esperar pelo Wi-Fi; uma tarefa à parte
// (tarefaRede, no outro núcleo do ESP32) monta e manda os pacotes. Assim um atraso da rede não faz perder passagem do disco.
#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
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

// ===== LEDS INDIVIDUAIS =====
const int leds[3] = {13, 12, 14};

bool detectado[9] = {false};

// ===== FITA WS2812B =====
#define PINO_FITA 27
#define NUM_LEDS 30
#define NUM_GRUPOS 9

Adafruit_NeoPixel fita(
  NUM_LEDS,
  PINO_FITA,
  NEO_GRB + NEO_KHZ800
);

// Cores das nove bobinas
const uint8_t cores[9][3] = {
  {255,   0,   0},  // 1 Vermelho
  {255,  82,   0},  // 2 Laranja
  {255, 176,   0},  // 3 Ambar
  {255, 255,   0},  // 4 Amarelo
  {  0, 255,   0},  // 5 Verde
  {  0, 255, 255},  // 6 Ciano
  {  0,  96, 255},  // 7 Azul
  {102,   0, 255},  // 8 Indigo
  {192,   0, 255}   // 9 Violeta
};

// Acende somente o grupo da bobina detectada
void acenderGrupo(int bobina) {
  if (bobina < 0 || bobina >= NUM_GRUPOS) {
    return;
  }

  int inicio = bobina * NUM_LEDS / NUM_GRUPOS;
  int fim = (bobina + 1) * NUM_LEDS / NUM_GRUPOS;

  for (int i = inicio; i < fim; i++) {
    fita.setPixelColor(
      i,
      fita.Color(
        cores[bobina][0],
        cores[bobina][1],
        cores[bobina][2]
      )
    );
  }

  fita.show();
}

// ===== CONFIGURACOES =====
const int LIMIAR = 10;
// [ESME] rev 5: tabela de pontos do conceito. O placar mostra a nota da bobina MAIS ALTA atingida na tentativa
// (100·k², k = numero da bobina; o gol e um salto e o visor satura em 9999). Os pontos existem so na mesa.
const int PONTOS_BOBINA[9] = {100, 400, 900, 1600, 2500, 3600, 4900, 6400, 9999};

// [ESME] rev 5: interruptores (mude o numero ou use -D na compilacao).
#ifndef NOTA_NA_HORA
  #define NOTA_NA_HORA 0    // 1 = a nota da bobina toca no instante em que o disco a cruza; 0 = nao toca durante a jogada
#endif
#ifndef NOTAS_NO_FIM
  #define NOTAS_NO_FIM 1    // 1 = repete as notas das bobinas cruzadas quando a tentativa acaba (como na rev 4); 0 = silencio
#endif
#ifndef TESTE_RUIDO_NOTA
  #define TESTE_RUIDO_NOTA 0  // 1 = TESTE DE BANCADA do ruido do som (veja "TESTE DE RUIDO" abaixo). Deixe 0 para jogar.
#endif

// [ESME] rev 6: FILTRO DE RAJADA e VOLUME DAS NOTAS.
#ifndef FILTRO_RAJADA
  #define FILTRO_RAJADA 1   // 1 = liga o filtro (veja "FILTRO DE RAJADA"); 0 = como a rev 5 (cada bobina acima do LIMIAR vale na hora)
#endif
#ifndef VOLUME_NOTAS
  #define VOLUME_NOTAS 27   // 0 a 30; 25 = o do v15. O ruido que o som faz nas bobinas cresce com o volume: para testar, tente 10 a 15.
#endif
#if FILTRO_RAJADA
  #define TXT_FILTRO "filtro de rajada LIGADO"
#else
  #define TXT_FILTRO "filtro de rajada DESLIGADO"
#endif

const unsigned long TEMPO_NOTA = 100;
const unsigned long TEMPO_ABERTURA = 15000;

const unsigned long TEMPO_ESTABILIZACAO = 300;

// [ESME] Quantas leituras seguidas acima do LIMIAR valem como "o disco passou".
// 1 = igual ao v15. Se com o Wi-Fi ligado aparecer passagem falsa (bobina acendendo sozinha, com o valor
// da serial perto do LIMIAR), mude para 2.
#ifndef LEITURAS_SEGUIDAS
  #define LEITURAS_SEGUIDAS 1
#endif
uint8_t acima[9] = {0};

// [ESME] rev 6: estado do filtro de rajada (as regras e as explicacoes estao em "FILTRO DE RAJADA", perto do loop()).
const uint32_t JANELA_RAJADA_US    = 20000;   // uma bobina que dispara fica "candidata" por 20 ms antes de valer
const uint32_t MIN_US_POR_BOBINA   = 10000;   // 7 cm entre bobinas em 10 ms = 7 m/s: mais rapido que isso nao e disco (a tacada mais rapida gravada: ~4 m/s)
const int      SALTO_MAX_BOBINAS   = 2;       // vale ate 2 bobinas acima da mais alta ja cruzada (pode faltar UMA no caminho); 9 = sem essa regra
const unsigned long JANELA_SOM_MS  = 800;         // ...mas so enquanto o som pode estar tocando (ate 800 ms depois do ultimo comando de nota): fora disso qualquer bobina vale (teste de bancada)
const uint32_t SILENCIO_RUIDO_US   = 40000;   // depois de descartar uma rajada, 40 ms sem aceitar nada novo (a maior rajada gravada durou 29 ms)
bool     candidata[9]    = {false};           // disparou e esta esperando a janela fechar
bool     bloqueada[9]    = {false};           // descartada: so volta a valer depois de cair abaixo do LIMIAR
uint32_t candInstante[9] = {0};
int      candValor[9]    = {0};
bool     janelaAberta    = false;
uint32_t janelaInicio    = 0;
bool     emRuido         = false;
uint32_t ruidoUltimo     = 0;
int      ultimaAceita    = -1;                // indice da ultima bobina aceita e o instante dela (para a regra de velocidade)
uint32_t ultimaAceitaInstante = 0;

int pontos = 0;
int bobinaMaisAlta = -1;       // [ESME] indice (0..8) da bobina mais alta cruzada nesta tentativa; -1 = nenhuma
bool notasTocadas = false;     // [ESME] "o fim desta tentativa ja foi tratado" (so o aviso da serial, ou as notas se NOTAS_NO_FIM)

// ===== BOTAO ===== [ESME]
// Um botao so, entre o pino e o GND (o ESP32 ja puxa o pino para cima por dentro).
const int PINO_BOTAO = 15;                           // o botao do v15: aperto curto = nova tentativa; segurar 3 s = nova sessao
const unsigned long TEMPO_NOVA_SESSAO_MS = 3000;
const unsigned long DEBOUNCE_BOTAO = 40;

// ===== CONTROLE DE ESTABILIZACAO =====
bool aguardandoEstabilizacao = false;
unsigned long inicioEstabilizacao = 0;
bool contandoEstabilizacao = false;
unsigned long esperaDesde = 0, ultimoAviso = 0;      // [ESME] so para avisar na serial se a estabilizacao demora

// ===== DISPLAY TM1637 =====
const int CLK = 21;
const int DIO = 4;

const byte segmentos[10] = {
  0x3F, 0x06, 0x5B, 0x4F, 0x66,
  0x6D, 0x7D, 0x07, 0x7F, 0x6F
};

void iniciarDisplay() {
  pinMode(CLK, OUTPUT);
  pinMode(DIO, OUTPUT);

  digitalWrite(CLK, HIGH);
  digitalWrite(DIO, HIGH);
}

void inicioTM() {
  digitalWrite(DIO, HIGH);
  digitalWrite(CLK, HIGH);
  delayMicroseconds(5);
  digitalWrite(DIO, LOW);
  delayMicroseconds(5);
  digitalWrite(CLK, LOW);
}

void fimTM() {
  digitalWrite(CLK, LOW);
  digitalWrite(DIO, LOW);
  delayMicroseconds(5);
  digitalWrite(CLK, HIGH);
  delayMicroseconds(5);
  digitalWrite(DIO, HIGH);
}

void escreverTM(byte dado) {
  for (int i = 0; i < 8; i++) {
    digitalWrite(CLK, LOW);
    digitalWrite(DIO, (dado >> i) & 1);
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

  digitalWrite(DIO, LOW);
  pinMode(DIO, OUTPUT);
}

void mostrarPontos(int numero) {
  numero = constrain(numero, 0, 9999);

  byte digitos[4];

  for (int i = 3; i >= 0; i--) {
    digitos[i] = segmentos[numero % 10];
    numero /= 10;
  }

  inicioTM();
  escreverTM(0x40);
  fimTM();

  inicioTM();
  escreverTM(0xC0);

  for (int i = 0; i < 4; i++) {
    escreverTM(digitos[i]);
  }

  fimTM();

  inicioTM();
  escreverTM(0x8F);
  fimTM();
}

// [ESME] Placar "-- --": e o que o site manda esperar depois do aperto de 3 s (nova sessao).
// Mesma sequencia de mostrarPontos(), so que com o traco do meio (0x40) nos quatro digitos.
void mostrarTracos() {
  inicioTM();
  escreverTM(0x40);
  fimTM();

  inicioTM();
  escreverTM(0xC0);

  for (int i = 0; i < 4; i++) {
    escreverTM(0x40);
  }

  fimTM();

  inicioTM();
  escreverTM(0x8F);
  fimTM();
}

// ===== PLACA MP3 =====
HardwareSerial mp3(2);

void comando(byte cmd, int parametro) {
  byte pacote[10] = {
    0x7E, 0xFF, 0x06, cmd, 0x00,
    (byte)(parametro >> 8),
    (byte)(parametro & 0xFF),
    0x00, 0x00, 0xEF
  };

  int soma = 0;
  for (int i = 1; i <= 6; i++) {
    soma += pacote[i];
  }

  int checksum = -soma;

  pacote[7] = (byte)(checksum >> 8);
  pacote[8] = (byte)(checksum & 0xFF);

  mp3.write(pacote, 10);
  delay(100);
}

void volumeMP3(int volume) {
  comando(0x06, volume);
}

void tocarFaixa(int faixa) {
  // Mantida ordem de gravacao no cartao
  comando(0x03, faixa);
}

void pararMP3() {
  comando(0x16, 0);
}

// ===== NOTA NA HORA ===== [ESME] rev 5
// O modulo MP3 toca UMA faixa por vez (um comando novo corta o anterior) e precisa de ~100 ms entre um comando e outro
// (o v15 espera 100 ms dentro de comando()). Se a nota do cruzamento usasse comando(), a mesa ficaria 100 ms sem ler
// nenhuma bobina e perderia passagens (as bobinas ficam a 7 cm uma da outra). Por isso aqui o envio NAO espera:
//   - agendarNota() deixa a nota "pendente"; servirNota(), chamada a cada volta do loop(), manda o comando assim que
//     passaram INTERVALO_COMANDO_MP3 ms do comando anterior, sem parar a leitura das bobinas;
//   - se outra bobina cruzar antes de a pendente sair, a mais recente vence (vale a posicao atual do disco).
const unsigned long INTERVALO_COMANDO_MP3 = 100;
int notaPendente = 0;                       // faixa (2..10) esperando para sair; 0 = nenhuma
unsigned long notaPendenteDesde = 0;        // millis() em que ela foi pedida
unsigned long ultimoComandoMP3 = 0;         // millis() do ultimo comando mandado sem esperar

// Mesmo pacote de comando(), mas sem o delay(100).
void comandoSemEspera(byte cmd, int parametro) {
  byte pacote[10] = {
    0x7E, 0xFF, 0x06, cmd, 0x00,
    (byte)(parametro >> 8),
    (byte)(parametro & 0xFF),
    0x00, 0x00, 0xEF
  };

  int soma = 0;
  for (int i = 1; i <= 6; i++) {
    soma += pacote[i];
  }

  int checksum = -soma;

  pacote[7] = (byte)(checksum >> 8);
  pacote[8] = (byte)(checksum & 0xFF);

  mp3.write(pacote, 10);
}

void agendarNota(int faixa, unsigned long atrasoMs = 0) {   // atrasoMs: quanto ja passou desde o cruzamento (rev 6: a janela do filtro)
  if (notaPendente != 0) {
    Serial.print("Nota da faixa ");
    Serial.print(notaPendente);
    Serial.println(" descartada: outra bobina cruzou antes de ela sair");
  }
  notaPendente = faixa;
  notaPendenteDesde = millis() - atrasoMs;
}

void servirNota() {
  if (notaPendente == 0) return;
  if (millis() - ultimoComandoMP3 < INTERVALO_COMANDO_MP3) return;

  int faixa = notaPendente;
  notaPendente = 0;
  comandoSemEspera(0x03, faixa);
  ultimoComandoMP3 = millis();

  Serial.print("Nota: faixa ");
  Serial.print(faixa);
  Serial.print(" (saiu ");
  Serial.print(ultimoComandoMP3 - notaPendenteDesde);
  Serial.println(" ms depois do cruzamento)");
}

void musicaAbertura() {
  Serial.println("Musica de abertura: faixa 1");

  volumeMP3(20);
  delay(300);

  tocarFaixa(1);
  delay(TEMPO_ABERTURA);

  pararMP3();
  delay(300);

  volumeMP3(25);

  Serial.println("Abertura encerrada");
}

// ===== MULTIPLEXADOR =====
void selecionarBobina(int canal) {
  digitalWrite(S0, canal & 0x01);
  digitalWrite(S1, (canal >> 1) & 0x01);
  digitalWrite(S2, (canal >> 2) & 0x01);
  digitalWrite(S3, (canal >> 3) & 0x01);
}

// ===== ESTADO DA MESA (compartilhado com a tarefa do Wi-Fi) ===== [ESME]
MesaLogica mesa;
portMUX_TYPE travaMesa = portMUX_INITIALIZER_UNLOCKED;
#define TRAVAR()  portENTER_CRITICAL(&travaMesa)      // trechos curtos: so mexem nas regras, nunca esperam nada
#define LIBERAR() portEXIT_CRITICAL(&travaMesa)

// ===== PLACAR ZERADO ===== [ESME]
// Nova tentativa ou nova sessao: faz o que o "nova jogada" do v15 fazia (para o som, apaga LEDs e fita,
// esquece as bobinas ja cruzadas e volta o placar a zero).
void zerarPlacar() {
  notaPendente = 0;                                     // [ESME] rev 5: uma nota que ainda nao saiu nao toca na tentativa seguinte
  pararMP3();

  pontos = 0;
  bobinaMaisAlta = -1;
  notasTocadas = false;

  for (int i = 0; i < 9; i++) {
    detectado[i] = false;
    acima[i] = 0;
    candidata[i] = false;                               // [ESME] rev 6: o filtro de rajada recomeca limpo
    bloqueada[i] = false;
  }
  janelaAberta = false;
  emRuido = false;
  ultimaAceita = -1;

  // Apaga os tres LEDs individuais
  for (int i = 0; i < 3; i++) {
    digitalWrite(leds[i], LOW);
  }

  // Apaga toda a fita
  fita.clear();
  fita.show();

  mostrarPontos(0);
}

// ===== ESTABILIZACAO =====
// As bobinas precisam ficar quietas (todas abaixo do LIMIAR) por TEMPO_ESTABILIZACAO antes de a tentativa contar.
void esperarEstabilizacao() {
  aguardandoEstabilizacao = true;
  contandoEstabilizacao = false;
  inicioEstabilizacao = 0;
  esperaDesde = ultimoAviso = millis();
}

void verificarEstabilizacao() {
  bool todosAbaixo = true;
  int maior = 0, qual = 0;

  for (int i = 0; i < 9; i++) {
    selecionarBobina(i);
    delayMicroseconds(100);

    int valor = analogRead(PINO_LEITURA);

    if (valor > LIMIAR) {
      todosAbaixo = false;
      if (valor > maior) {
        maior = valor;
        qual = i;
      }
    }
  }

  if (!todosAbaixo) {
    contandoEstabilizacao = false;

    if (millis() - ultimoAviso >= 3000) {            // [ESME] nao acalma: mostra quem esta acima do LIMIAR
      ultimoAviso = millis();
      Serial.print("Estabilizacao demorando: bobina ");
      Serial.print(qual + 1);
      Serial.print(" lendo ");
      Serial.println(maior);
    }
    return;
  }

  if (!contandoEstabilizacao) {
    inicioEstabilizacao = millis();
    contandoEstabilizacao = true;
  }

  if (millis() - inicioEstabilizacao >=
      TEMPO_ESTABILIZACAO) {
    aguardandoEstabilizacao = false;
    contandoEstabilizacao = false;

    Serial.println("Bobinas estabilizadas");
    Serial.println("Sistema pronto para jogar");
  }
}

// ===== BOTOES ===== [ESME]
// Filtra a "tremida" do contato: so muda de estado depois de DEBOUNCE_BOTAO estavel.
struct BotaoFiltrado {
  int pino;
  bool apertado;          // estado ja filtrado
  bool bruto;
  bool jaSoltou;          // ja foi visto SOLTO alguma vez (pino preso em LOW desde a partida nunca chega a "jaSoltou")
  unsigned long desde;
  explicit BotaoFiltrado(int p) : pino(p), apertado(false), bruto(false), jaSoltou(false), desde(0) {}
  // "valido" = apertado de verdade: um pino que ja le LOW ao ligar (botao preso, fio no GND, apertado durante a musica)
  // so passa a valer depois de ser visto solto uma vez. Sem isso a mesa se destravava sozinha ~3 s depois de ligar
  // e o site, que so percebe a MUDANCA do contador de sessao, nunca via o aperto.
  bool valido() const { return apertado && jaSoltou; }
  void atualizar() {
    bool agoraBruto = (digitalRead(pino) == LOW);
    unsigned long agora = millis();
    if (agoraBruto != bruto) { bruto = agoraBruto; desde = agora; }
    if (bruto != apertado && agora - desde >= DEBOUNCE_BOTAO) apertado = bruto;
    if (!bruto && !apertado) jaSoltou = true;
  }
};

// Conta os 3 s do botao. completou() devolve true UMA vez por aperto, no instante em que o botao completa 3 s.
struct SegurarTres {
  bool contando = false, disparou = false;
  unsigned long desde = 0;
  bool completou(bool apertado) {
    if (!apertado) { contando = false; disparou = false; return false; }
    if (!contando) { contando = true; desde = millis(); }
    if (!disparou && millis() - desde >= TEMPO_NOVA_SESSAO_MS) { disparou = true; return true; }
    return false;
  }
};

BotaoFiltrado botao(PINO_BOTAO);

void novaTentativa() {
  TRAVAR();
  bool aceitou = mesaNovaTentativa(mesa, micros());
  LIBERAR();

  if (!aceitou) {
    Serial.println("Mesa travada: segure o botao por 3 s (nova sessao)");
    return;
  }

  zerarPlacar();
  esperarEstabilizacao();

  Serial.println("====================");
  Serial.println("NOVA TENTATIVA");
  Serial.println("Aguardando estabilizacao");
  Serial.println("====================");
}

void novaSessao() {
  TRAVAR();
  mesaNovaSessao(mesa, micros());
  LIBERAR();

  zerarPlacar();
  mostrarTracos();                                      // o site pede para esperar o placar mostrar "-- --"
  aguardandoEstabilizacao = false;                      // a mesa fica "pronta": so conta depois de "nova tentativa"

  Serial.println("====================");
  Serial.println("NOVA SESSAO");
  Serial.println("Aperte NOVA TENTATIVA para jogar");
  Serial.println("====================");
}

// Escreve na serial o nivel do pino do botao. Na partida isso mostra de cara um pino que "nasce" apertado.
void mostrarEntradas(const char* quando) {
  Serial.print("Entradas ");
  Serial.print(quando);
  Serial.print(": GPIO 15 (botao) = ");
  Serial.println(digitalRead(PINO_BOTAO) == LOW ? "LOW (apertado ou preso)" : "HIGH (solto)");
}

// O botao unico. Aperto curto = nova tentativa (age ao SOLTAR, se nao virou "nova sessao"); segurar 3 s = nova sessao
// (age no instante em que completa os 3 s, uma vez por aperto). Um pino que ja le LOW na partida (preso, ou apertado
// durante a musica) e ignorado ate ser solto uma vez.
void lerBotao() {
  static bool apertadoAntes = false, avisouPreso = false, sessaoPedida = false;
  static unsigned long apertadoDesde = 0;
  static SegurarTres segurar3s;

  botao.atualizar();
  bool apertado = botao.valido();
  if (botao.apertado && !botao.jaSoltou && !avisouPreso) {
    avisouPreso = true;
    Serial.println("Aviso: GPIO 15 le LOW desde a partida (botao apertado ao ligar ou preso): ignorado ate soltar");
  }

  if (apertado && !apertadoAntes) {
    apertadoDesde = millis();
    sessaoPedida = false;
    Serial.println("Botao (GPIO 15) apertado");
  }

  if (segurar3s.completou(apertado)) {                  // segurou 3 s: nova sessao, em qualquer estado da mesa
    sessaoPedida = true;
    novaSessao();
  }

  if (!apertado && apertadoAntes) {
    Serial.print("Botao (GPIO 15) solto apos ");
    Serial.print(millis() - apertadoDesde);
    Serial.println(" ms");
    if (!sessaoPedida) novaTentativa();                 // aperto curto: so vale com a sessao criada (mesa travada recusa)
  }
  apertadoAntes = apertado;
}

const char* nomeEstado(MesaEstado e) {
  switch (e) {
    case M_TRAVADA:       return "TRAVADA";
    case M_PRONTA:        return "PRONTA (aperte nova tentativa)";
    case M_ARMADA:        return "ARMADA (aguardando o disco)";
    case M_EM_TENTATIVA:  return "EM TENTATIVA";
    default:              return "FIM";
  }
}
// ===== FESTA DO GOL =====
// Quando a tentativa acaba em gol: LUZ e SOM.
//   LUZ: (1) as 9 cores da fita correm ate o fim, (2) a fita inteira pisca 3 vezes nas cores normais, (3) a fita volta ao que
//        estava (so os grupos das bobinas cruzadas). O placar (9999) nao muda.
//   SOM: um TRINADO (duas notas agudas se alternando) durante a corrida e um "ta-ta-TA" (uma nota por piscada, subindo) nas
//        piscadas. Sao as mesmas faixas das notas (2 a 10): troque os numeros abaixo e ouca ate gostar.
// Dura uns 2 s e trava o loop, como a repeticao das notas: nesse tempo o botao nao e lido. As bobinas nao sao lidas depois do
// gol, entao a festa (nem o som dela) nao atrapalha a leitura.
const int FESTA_QUADROS = 40;         // quadros do arco-iris correndo
const int FESTA_QUADRO_MS = 30;       // duracao de cada quadro (40 x 30 ms = 1,2 s)
const int FESTA_PISCADAS = 3;         // quantas vezes a fita inteira pisca
const int FESTA_PISCADA_MS = 120;     // aceso 120 ms, apagado 120 ms
const uint8_t FESTA_BRILHO = 60;      // brilho durante a festa (o normal e 60). So suba (ex.: 120) se a fonte da fita aguentar.

const bool FESTA_COM_SOM = true;                        // false = festa so de luz
const int FESTA_NOTAS_TRINADO[2] = {9, 10};             // as 2 faixas que se alternam durante a corrida
const int FESTA_TRINADO_MS = 200;                       // intervalo entre as notas do trinado. NAO baixe de 200: o modulo MP3 corta a nota anterior antes de ela tocar
const int FESTA_NOTAS_PISCADAS[FESTA_PISCADAS] = {6, 8, 10};   // uma faixa por piscada (a ultima fecha a festa). Faixa 0 = sem nota nessa piscada
const int FESTA_ANTECIPA_MS = 150;                      // o modulo demora um pouco para comecar a tocar: a nota sai este tempo ANTES da piscada. Som atrasado em relacao a luz? aumente (ate 200). Adiantado? diminua.
#if NOTAS_NO_FIM
  const int FESTA_SOM_INICIO_MS = 0;                    // as notas repetidas acabaram agora: o trinado continua no mesmo ritmo delas
#else
  const int FESTA_SOM_INICIO_MS = 400;                  // a nota do gol (nota na hora) acabou de sair: deixa ela tocar antes do trinado
#endif

struct FestaSom { uint16_t quando; uint8_t faixa; };    // quando = ms depois do comeco da festa
const int FESTA_SONS_MAX = 24;
FestaSom festaSons[FESTA_SONS_MAX];
int festaSonsN = 0, festaSonsProx = 0;
uint32_t festaInicio = 0;

void festaSomAdiciona(int quando, int faixa) {
  if (faixa <= 0 || quando < 0 || festaSonsN >= FESTA_SONS_MAX) return;
  festaSons[festaSonsN].quando = quando;
  festaSons[festaSonsN].faixa = faixa;
  festaSonsN++;
}

// Monta a lista de sons da festa: o trinado ocupa a corrida, ate 200 ms antes da nota da 1a piscada; depois, uma nota por piscada.
void festaSomMonta() {
  festaSonsN = 0;
  festaSonsProx = 0;
  if (!FESTA_COM_SOM) return;
  int inicioPiscadas = FESTA_QUADROS * FESTA_QUADRO_MS;
  int primeiraNota = inicioPiscadas - FESTA_ANTECIPA_MS;
  for (int t = FESTA_SOM_INICIO_MS, k = 0; t + FESTA_TRINADO_MS <= primeiraNota; t += FESTA_TRINADO_MS, k++)
    festaSomAdiciona(t, FESTA_NOTAS_TRINADO[k % 2]);
  for (int k = 0; k < FESTA_PISCADAS; k++)
    festaSomAdiciona(inicioPiscadas + k * 2 * FESTA_PISCADA_MS - FESTA_ANTECIPA_MS, FESTA_NOTAS_PISCADAS[k]);
}

// Manda o proximo som da festa quando chega a hora (sem esperar: o comando nao trava, como servirNota()).
void festaSomServe() {
  if (festaSonsProx >= festaSonsN) return;
  if (millis() - festaInicio < festaSons[festaSonsProx].quando) return;
  if (millis() - ultimoComandoMP3 < INTERVALO_COMANDO_MP3) return;
  int faixa = festaSons[festaSonsProx].faixa;
  festaSonsProx++;
  comandoSemEspera(0x03, faixa);
  ultimoComandoMP3 = millis();
  Serial.print("Festa: faixa ");
  Serial.println(faixa);
}

// espera 'ms' milissegundos, mas a cada 1 ms confere a nota pendente do gol e os sons da festa (como o loop() faz)
void festaEspera(uint32_t ms) {
  uint32_t inicio = millis();
  while (millis() - inicio < ms) {
    servirNota();
    festaSomServe();
    delay(1);
  }
}

void festaGol() {
  Serial.println("GOL! Festa na fita");
  festaInicio = millis();
  festaSomMonta();
  uint8_t brilhoNormal = fita.getBrightness();
  fita.setBrightness(FESTA_BRILHO);

  int grupoDe[NUM_LEDS];                                  // a que grupo (bobina) cada led pertence, como em acenderGrupo()
  for (int g = 0; g < NUM_GRUPOS; g++)
    for (int p = g * NUM_LEDS / NUM_GRUPOS; p < (g + 1) * NUM_LEDS / NUM_GRUPOS; p++) grupoDe[p] = g;

  for (int q = 0; q < FESTA_QUADROS; q++) {               // 1) arco-iris correndo na direcao do gol
    for (int p = 0; p < NUM_LEDS; p++) {
      const uint8_t* c = cores[grupoDe[(p - q % NUM_LEDS + NUM_LEDS) % NUM_LEDS]];
      fita.setPixelColor(p, fita.Color(c[0], c[1], c[2]));
    }
    fita.show();
    festaEspera(FESTA_QUADRO_MS);
  }

  for (int k = 0; k < FESTA_PISCADAS; k++) {              // 2) a fita inteira pisca de uma vez, nas cores normais
    for (int p = 0; p < NUM_LEDS; p++) {
      const uint8_t* c = cores[grupoDe[p]];
      fita.setPixelColor(p, fita.Color(c[0], c[1], c[2]));
    }
    fita.show();
    festaEspera(FESTA_PISCADA_MS);
    fita.clear();
    fita.show();
    festaEspera(FESTA_PISCADA_MS);
  }

  fita.setBrightness(brilhoNormal);                       // 3) a fita volta ao que estava: so os grupos das bobinas cruzadas
  for (int p = 0; p < NUM_LEDS; p++) {
    if (detectado[grupoDe[p]]) {
      const uint8_t* c = cores[grupoDe[p]];
      fita.setPixelColor(p, fita.Color(c[0], c[1], c[2]));
    } else {
      fita.setPixelColor(p, 0);
    }
  }
  fita.show();
}

// ===== REPRODUCAO DAS NOTAS =====
// Como no v15, so toca depois da jogada. [ESME] "depois da jogada" = a tentativa acabou (gol, ou 3 s sem avancar).
void tocarNotasDetectadas() {
  Serial.println("Reproduzindo notas detectadas");

  notasTocadas = true;

  for (int i = 0; i < 9; i++) {
    if (detectado[i]) {
      tocarFaixa(i + 2);

      Serial.print("Nota da bobina ");
      Serial.println(i + 1);

      delay(TEMPO_NOTA);
    }
  }

  Serial.println("Fim das notas");
  Serial.println("Pressione NOVA TENTATIVA");
}

// ===== WI-FI NO OUTRO NUCLEO ===== [ESME]
// Tudo que fala com a rede fica aqui (inclusive o esmeServico: USB, Wi-Fi e aviso do IP).
// A cada 100 ms manda o estado inteiro da mesa e os eventos dos ultimos 2 s.
void tarefaRede(void*) {
  uint8_t pacote[MESA_PACOTE_MAX];
  bool tinhaWifi = false, podiaEnviar = false;
  unsigned long proximo = millis();

  for (;;) {
    esmeServico();

    bool temWifi = esmeConectado();
    if (temWifi && !tinhaWifi) WiFi.setSleep(false);    // sem economia de energia do Wi-Fi: menos atraso e menos variacao
    if (temWifi != tinhaWifi) Serial.println(temWifi ? "Wi-Fi conectado" : "Wi-Fi caiu");
    tinhaWifi = temWifi;

    bool podeEnviar = esmePodeEnviar();                 // avisa na serial quando a mesa comeca/para de falar com o site
    if (podeEnviar != podiaEnviar) Serial.println(podeEnviar ? "Site: enviando o estado da mesa" : "Site: parou de enviar (sem Wi-Fi ou sem destino)");
    podiaEnviar = podeEnviar;

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

// ===== TESTE DE RUIDO DO SOM (so com TESTE_RUIDO_NOTA 1) ===== [ESME] rev 5
// Pergunta que ele responde: o som do modulo MP3 atrapalha a leitura das bobinas? Como usar: grave com TESTE_RUIDO_NOTA 1,
// abra o Serial Monitor (115200), faca "nova sessao" (segurar 3 s) e "nova tentativa" (aperto curto) e NAO passe o disco.
// Quando aparecer "Sistema pronto para jogar", a mesa toca as notas 2 a 10, uma a cada 1,5 s, e mostra para cada uma o
// MAIOR valor lido em cada bobina durante o som e nos ~900 ms de silencio antes dele. Sem disco, qualquer valor acima do
// "silencio" e ruido do som. Se chegar perto do LIMIAR (70) a nota vai disparar passagem falsa. Se passar do LIMIAR a
// propria mesa mostra "Bobina N detectada" (e a tentativa comeca): e a falha real.
#if TESTE_RUIDO_NOTA
int picoLido[9] = {0};
int picoSilencio[9] = {0};
int testeFaixa = 2;
bool testeJanela = false, testeIniciado = false;
unsigned long testeProxima = 0, testeFimJanela = 0;

void testeRuidoLerBobina(int i, int valor) {
  if (valor > picoLido[i]) picoLido[i] = valor;
}

void testeRuidoImprimir(const char* rotulo, int* v) {
  Serial.print(rotulo);
  for (int i = 0; i < 9; i++) {
    Serial.print(' ');
    Serial.print(v[i]);
  }
  Serial.println();
}

void testeRuido() {
  unsigned long agora = millis();
  if (!testeIniciado) {
    testeIniciado = true;
    testeProxima = agora + 1500;
    for (int i = 0; i < 9; i++) picoLido[i] = 0;
    Serial.println("TESTE DE RUIDO: nao passe o disco. Vou tocar as notas 2 a 10.");
  }
  if (testeJanela && agora >= testeFimJanela) {
    Serial.print("TESTE DE RUIDO faixa ");
    Serial.print(testeFaixa);
    Serial.println(" (valores das bobinas 1 a 9, LIMIAR 70):");
    testeRuidoImprimir("   silencio antes:", picoSilencio);
    testeRuidoImprimir("   durante o som :", picoLido);
    for (int i = 0; i < 9; i++) picoLido[i] = 0;
    testeJanela = false;
    testeFaixa++;
    if (testeFaixa > 10) Serial.println("Fim do teste de ruido");
  } else if (!testeJanela && testeFaixa <= 10 && agora >= testeProxima) {
    for (int i = 0; i < 9; i++) { picoSilencio[i] = picoLido[i]; picoLido[i] = 0; }
    agendarNota(testeFaixa);
    servirNota();
    testeJanela = true;
    testeFimJanela = agora + 600;
    testeProxima = agora + 1500;
  }
}
#endif

// ===== SETUP =====
void setup() {
  Serial.begin(115200);
  Serial.println("mesa_esme: v15 + site rev 6 (placar 100*k^2 pela bobina mais alta; nota na hora do cruzamento; " TXT_FILTRO "; UM botao: aperto curto = nova tentativa, segurar 3 s = nova sessao)");

  esmeIniciar();                                        // [ESME] le o Wi-Fi guardado na placa e comeca a conectar
  mesaIniciar(mesa, (uint16_t)(esp_random() & 0xFFFF)); // [ESME] a mesa liga travada

  pinMode(S0, OUTPUT);
  pinMode(S1, OUTPUT);
  pinMode(S2, OUTPUT);
  pinMode(S3, OUTPUT);

  pinMode(PINO_BOTAO, INPUT_PULLUP);
  delay(20);                                            // [ESME] deixa o pull-up firmar antes de olhar o nivel
  mostrarEntradas("ao ligar");                          // [ESME] LOW aqui = botao apertado ou pino preso

  // Somente tres LEDs individuais
  for (int i = 0; i < 3; i++) {
    pinMode(leds[i], OUTPUT);
    digitalWrite(leds[i], LOW);
  }

  // Inicializa a fita WS2812B
  fita.begin();
  fita.setBrightness(60);
  fita.clear();
  fita.show();

  analogReadResolution(12);

  iniciarDisplay();
  mostrarPontos(0);

  // [ESME] a tarefa do Wi-Fi comeca ja, antes da musica: o site ve a mesa "Conectada" (travada) sem esperar os 15 s
  xTaskCreatePinnedToCore(tarefaRede, "rede", 10240, nullptr, 1, nullptr, 0);

  mp3.begin(9600, SERIAL_8N1, 16, 17);
  delay(1500);

  musicaAbertura();
#if VOLUME_NOTAS != 25
  volumeMP3(VOLUME_NOTAS);                              // [ESME] rev 6: a abertura usa o volume do v15; as notas, este
  Serial.print("Volume das notas: ");
  Serial.println(VOLUME_NOTAS);
#endif

  mostrarEntradas("apos a musica");                     // [ESME] se um botao estiver apertado agora, so vale depois de soltar
  Serial.println("Sistema iniciado. Mesa TRAVADA: segure o botao por 3 s (nova sessao).");
}
// ===== BOBINA 7 COM MAL CONTATO =====
// Se o disco cruza a bobina 8 e a 7 nao foi lida nesta tentativa, a 7 e registrada na hora, como se tivesse sido lida
// (placar, fita, nota e evento para o site). A hora dela e estimada entre a ultima bobina aceita e a 8.
// Chamada no comeco de registrarCruzamento(), so quando a bobina e a 8 (indice 7).
bool registrarCruzamento(int i, uint32_t instante, int valor);

void completarBobina7(uint32_t instanteDaOito) {
  const int B7 = 6, B8 = 7;                              // indices: bobina 7 = 6, bobina 8 = 7
  if (detectado[B7] || detectado[B8]) return;            // a 7 ja foi lida (ou a 8 ja contou): nada a fazer
  TRAVAR();
  bool emCurso = mesaEmCurso(mesa);                      // so vale dentro de uma tentativa
  LIBERAR();
  if (!emCurso) return;

  uint32_t t7 = instanteDaOito - 1000;                   // sem bobina anterior: 1 ms antes da 8
  if (ultimaAceita >= 0 && ultimaAceita < B7) {          // senao: proporcional as bobinas entre a ultima aceita e a 8
    uint32_t dt = instanteDaOito - ultimaAceitaInstante;
    t7 = ultimaAceitaInstante + (uint32_t)((uint64_t)dt * (B7 - ultimaAceita) / (B8 - ultimaAceita));
  }
  Serial.println("Bobina 7 sem leitura, mas o disco chegou na 8: bobina 7 assumida");
  registrarCruzamento(B7, t7, 0);
}
// ===== CRUZAMENTO DA BOBINA ===== [ESME] rev 6
// O que acontece quando o disco cruzou a bobina i: o que era o corpo do "if" do loop() ate a rev 5.
// `instante` = micros() da leitura. Com o filtro ligado ela chega ate JANELA_RAJADA_US depois de o disco passar; o instante
// ORIGINAL e o que vai para o pacote do site, entao o site nao percebe o atraso.
bool registrarCruzamento(int i, uint32_t instante, int valor) {
    if (i == 7) completarBobina7(instante);
  TRAVAR();                                           // [ESME] a mesa avisa o notebook (bobina i+1; a 9a e o gol)
  bool valeu = mesaCruzou(mesa, i + 1, instante);
  LIBERAR();
  if (!valeu) return false;                           // [ESME] fora da tentativa: nao conta

  detectado[i] = true;
  ultimaAceita = i;
  ultimaAceitaInstante = instante;

#if NOTA_NA_HORA
  agendarNota(i + 2, (uint32_t)(micros() - instante) / 1000);   // [ESME] rev 5: a nota da bobina sai AGORA (faixas 2 a 10)
  servirNota();
#endif

  // LEDs individuais: bobinas 1, 2 e 3
  if (i < 3) {
    digitalWrite(leds[i], HIGH);
  }

  // Fita: todas as nove bobinas
  acenderGrupo(i);

  bool subiu = false;                                 // [ESME] rev 5: o placar e a nota da bobina MAIS ALTA atingida;
  if (i > bobinaMaisAlta) {                           // uma bobina mais baixa, cruzada depois de uma mais alta, nao o reduz
    bobinaMaisAlta = i;
    pontos = PONTOS_BOBINA[i];
    mostrarPontos(pontos);
    subiu = true;
  }

  Serial.print("Bobina ");
  Serial.print(i + 1);
  Serial.print(" detectada. Valor: ");
  Serial.println(valor);
  if (subiu) {
    Serial.print("Placar: ");
    Serial.println(pontos);
  }
  return true;
}

// ===== FILTRO DE RAJADA ===== [ESME] rev 6
// POR QUE EXISTE: com a nota tocando na hora do cruzamento (rev 5), ~170 a 240 ms depois do comando o som do modulo MP3 faz
// 3 a 5 bobinas "dispararem" quase juntas (3 a 29 ms entre elas, fora de ordem, quase sempre com o gol): o placar pulava e a
// tentativa acabava em gol falso. Nos dados do site, 0 de 18 tentativas com a mesa em silencio tiveram isso; 12 de 14 com som
// na hora tiveram. Uma bobina que dispara fica "candidata" por JANELA_RAJADA_US; quando a janela fecha:
//   1. 3 ou mais bobinas, ou duas que o disco nao poderia ter cruzado naquele intervalo (mais rapido que 7 m/s) = ruido: todas
//      as candidatas sao descartadas;
//   2. uma bobina rapida demais depois da ultima aceita = ruido; e, ate 800 ms depois de uma nota, uma bobina longe demais
//      da maior ja cruzada (SALTO_MAX_BOBINAS) tambem, e o GOL sem a bobina 8 ja cruzada (todo gol verdadeiro gravado passou
//      pela 8; quase toda rajada falsa trazia o gol sozinho). O som so atrapalha logo depois de tocar: fora desses 800 ms
//      qualquer bobina vale (teste de bancada passando o disco numa bobina qualquer funciona);
//   3. o resto e passagem de verdade e entra com o instante original da leitura.
// Depois de descartar, nada novo vale ate o ruido acalmar (SILENCIO_RUIDO_US); a bobina descartada so volta a valer depois de
// cair abaixo do LIMIAR. Na serial: "Rajada descartada (...): bobinas ..." com o maior valor e quanto tempo faz da ultima nota.
// LIMITES: uma passagem real que caia JUNTO com a rajada (ou nos SILENCIO_RUIDO_US depois dela) e descartada com ela; e uma
// unica bobina nova, vizinha da maior (ou o gol logo depois da 8), nao se distingue de uma passagem real. O conserto de
// verdade e eletrico (alimentacao/fios do modulo MP3); isto e a rede de seguranca.
#if FILTRO_RAJADA
void candidatar(int i, uint32_t instante, int valor) {
  if (candidata[i] || bloqueada[i]) return;
  if (emRuido) {                                      // ainda no meio de uma rajada: nada novo vale
    bloqueada[i] = true;
    return;
  }
  candidata[i] = true;
  candInstante[i] = instante;
  candValor[i] = valor;
  if (!janelaAberta) {
    janelaAberta = true;
    janelaInicio = instante;
  }
}

void avaliarRajada() {
  uint32_t agora = micros();
  if (emRuido && (uint32_t)(agora - ruidoUltimo) >= SILENCIO_RUIDO_US) emRuido = false;
  if (!janelaAberta || (uint32_t)(agora - janelaInicio) < JANELA_RAJADA_US) return;
  janelaAberta = false;

  int ord[9], n = 0;                                  // as candidatas, em ordem de instante
  for (int i = 0; i < 9; i++) {
    if (candidata[i]) ord[n++] = i;
  }
  for (int a = 1; a < n; a++) {
    int x = ord[a], b = a - 1;
    while (b >= 0 && (int32_t)(candInstante[ord[b]] - candInstante[x]) > 0) {
      ord[b + 1] = ord[b];
      b--;
    }
    ord[b + 1] = x;
  }

  const char* motivo = nullptr;
  bool somRecente = (ultimoComandoMP3 != 0) && (millis() - ultimoComandoMP3 < JANELA_SOM_MS);
  if (n >= 3) motivo = "3 ou mais bobinas juntas";
  int maior = bobinaMaisAlta, ult = ultimaAceita;
  uint32_t ultInst = ultimaAceitaInstante;
  for (int k = 0; k < n && motivo == nullptr; k++) {
    int j = ord[k];
    if (somRecente && j > maior + SALTO_MAX_BOBINAS) {
      motivo = "bobina longe demais da maior ja cruzada";
    } else if (somRecente && j == 8 && maior < 7) {
      motivo = "gol sem a bobina 8 antes";
    } else if (ult >= 0 && (uint32_t)(candInstante[j] - ultInst) < (uint32_t)abs(j - ult) * MIN_US_POR_BOBINA) {
      motivo = "rapido demais para ser o disco";
    }
    if (j > maior) maior = j;
    ult = j;
    ultInst = candInstante[j];
  }

  if (motivo != nullptr) {
    int pico = 0;
    Serial.print("Rajada descartada (");
    Serial.print(motivo);
    Serial.print("): bobinas");
    for (int k = 0; k < n; k++) {
      Serial.print(' ');
      Serial.print(ord[k] + 1);
      if (candValor[ord[k]] > pico) pico = candValor[ord[k]];
      bloqueada[ord[k]] = true;
      candidata[ord[k]] = false;
    }
    Serial.print(" | maior valor ");
    Serial.print(pico);
    Serial.print(" | ");
    Serial.print(millis() - ultimoComandoMP3);
    Serial.println(" ms depois do ultimo comando de nota");
    emRuido = true;
    ruidoUltimo = agora;
    return;
  }

  for (int k = 0; k < n; k++) {
    candidata[ord[k]] = false;
    registrarCruzamento(ord[k], candInstante[ord[k]], candValor[ord[k]]);
  }
}
#endif

// ===== LOOP =====
void loop() {
  servirNota();                                         // [ESME] rev 5: manda a nota pendente assim que o modulo MP3 pode receber
  lerBotao();                                           // [ESME]

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

  if (botao.valido()) {                        // v15: com o botao apertado nao le nada (pino preso desde a partida nao conta)
    delay(1);
    return;
  }

  if (estado == M_FIM) {                                // [ESME] a tentativa acabou (uma vez so)
    if (!notasTocadas) {
#if NOTAS_NO_FIM
      tocarNotasDetectadas();                           // rev 4: repete as notas das bobinas cruzadas
      if (motivoFim == MOT_GOL) festaGol();             // [ESME] festa do gol, depois das notas
#else
      if (motivoFim == MOT_GOL) festaGol();             // [ESME] festa do gol
      notasTocadas = true;                              // rev 5: em silencio (a nota de cada bobina tocou na hora do cruzamento)
      Serial.println("Fim da tentativa");
      Serial.println("Pressione NOVA TENTATIVA");
#endif
    } else {
      delay(1);
    }
    return;
  }

  if (estado != M_ARMADA && estado != M_EM_TENTATIVA) { // [ESME] travada ou pronta: nao le as bobinas
    delay(1);
    return;
  }

  if (aguardandoEstabilizacao) {
    verificarEstabilizacao();
    return;
  }

  // Leitura das nove bobinas
  for (int i = 0; i < 9; i++) {
    selecionarBobina(i);
    delayMicroseconds(100);

    int valor = analogRead(PINO_LEITURA);
    uint32_t instante = micros();                       // [ESME] hora da leitura
#if TESTE_RUIDO_NOTA
    testeRuidoLerBobina(i, valor);
#endif

    if (valor > LIMIAR) {
      if (acima[i] < 255) acima[i]++;
    } else {
      acima[i] = 0;
    }

#if FILTRO_RAJADA
    if (valor <= LIMIAR) bloqueada[i] = false;          // [ESME] rev 6: a bobina descartada volta a valer depois de cair abaixo do LIMIAR
#endif

    if (acima[i] >= LEITURAS_SEGUIDAS && !detectado[i]) {
#if FILTRO_RAJADA
      candidatar(i, instante, valor);                   // [ESME] rev 6: espera a janela do filtro de rajada fechar
#else
      registrarCruzamento(i, instante, valor);          // [ESME] rev 6: era o corpo deste "if" ate a rev 5
#endif
    }
  }
#if FILTRO_RAJADA
  avaliarRajada();                                      // [ESME] rev 6: fecha a janela (se passou o tempo) e decide
#endif

#if TESTE_RUIDO_NOTA
  testeRuido();                                         // [ESME] so no teste de bancada: toca as notas e mede o ruido
#endif
}