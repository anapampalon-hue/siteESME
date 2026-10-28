// esme_config.h — Wi-Fi do ESME para ESP32 (mesa) e ESP8266 (batedor). Fica na MESMA pasta do .ino.
//
// O que faz:
//   1. Recebe o Wi-Fi pelo cabo USB (comandos "ESME?" e "CFG;..." — ver protocolo-serial.md) e guarda na memória da placa.
//   2. Depois de ligada (mesmo sem o cabo), conecta sozinha no Wi-Fi guardado e reconecta se cair.
//   3. Escuta o aviso do notebook ("ESME-IP;1;<ip>;<porta_mesa>;<porta_batedor>", UDP 4200) e usa o IP dele como destino.
//      Enquanto nenhum aviso chegou, usa o IP gravado pelo cabo (reserva).
//   4. esmeEnviar() manda um pacote UDP para o notebook.
//
// Como usar no sketch (ANTES do #include):
//   #define ESME_TIPO         "MESA"      // ou "BATEDOR"
//   #define ESME_VERSAO       "1.0"
//   #define ESME_PORTA_DADOS  4212        // mesa 4212, batedor 4210
//   #include "esme_config.h"
//   setup():  Serial.begin(115200); esmeIniciar();
//   loop():   esmeServico();   (chamar sempre, e dentro de qualquer espera longa)
//   enviar:   esmeEnviar(bytes, tamanho);
//
// A senha do Wi-Fi nunca é impressa na serial.
#pragma once
#include <Arduino.h>
#include <EEPROM.h>
#include <WiFiUdp.h>
#if defined(ESP32)
  #include <WiFi.h>
#elif defined(ESP8266)
  #include <ESP8266WiFi.h>
#else
  #error "esme_config.h: só ESP32 e ESP8266."
#endif

#ifndef ESME_TIPO
  #error "Defina ESME_TIPO (\"MESA\" ou \"BATEDOR\") antes de incluir esme_config.h"
#endif
#ifndef ESME_VERSAO
  #define ESME_VERSAO "1.0"
#endif
#ifndef ESME_PORTA_DADOS
  #define ESME_PORTA_DADOS 4212
#endif
#define ESME_PORTA_ANUNCIO     4200
#define ESME_TEMPO_WIFI_MS     20000UL   // quanto esperar para entrar no Wi-Fi ao receber CFG
#define ESME_REGRAVAR_WIFI_MS  15000UL   // sem Wi-Fi por tanto tempo: tenta conectar de novo

// ---------------------------------------------------------------- memória (EEPROM) ----------
struct EsmeRede {
  uint32_t magia;      // 'ESME' quando há rede gravada
  char ssid[33];
  char senha[64];
  char ip[16];         // IP do notebook gravado pelo cabo (reserva)
  uint8_t soma;
};
static const uint32_t ESME_MAGIA = 0x454D5345UL;

static EsmeRede  _esmeRede;
static bool      _esmeTemRede = false;
static IPAddress _esmeDestino;          // para onde vão os pacotes
static bool      _esmeTemDestino = false;
static uint16_t  _esmePorta = ESME_PORTA_DADOS;
static WiFiUDP   _esmeUdpEnvio;
static WiFiUDP   _esmeUdpAnuncio;
static bool      _esmeEscutando = false;
static unsigned long _esmeUltimaChecagem = 0, _esmeSemWifiDesde = 0, _esmeUltimoAnuncio = 0;

static uint8_t _esmeSoma(const EsmeRede& r) {
  const uint8_t* p = (const uint8_t*)&r;
  uint8_t s = 0;
  for (size_t i = 0; i < offsetof(EsmeRede, soma); i++) s += p[i];
  return s;
}

static bool _esmeGravarRede() {
  _esmeRede.magia = ESME_MAGIA;
  _esmeRede.soma = _esmeSoma(_esmeRede);
  EEPROM.put(0, _esmeRede);
  return EEPROM.commit();
}

static bool _esmeLerRede() {
  EEPROM.get(0, _esmeRede);
  if (_esmeRede.magia != ESME_MAGIA || _esmeRede.soma != _esmeSoma(_esmeRede)) return false;
  _esmeRede.ssid[32] = 0; _esmeRede.senha[63] = 0; _esmeRede.ip[15] = 0;
  return _esmeRede.ssid[0] != 0;
}

// ---------------------------------------------------------------- base64 ----------
static int _esmeB64Valor(char c) {
  if (c >= 'A' && c <= 'Z') return c - 'A';
  if (c >= 'a' && c <= 'z') return c - 'a' + 26;
  if (c >= '0' && c <= '9') return c - '0' + 52;
  if (c == '+') return 62;
  if (c == '/') return 63;
  return -1;
}

// devolve o tamanho decodificado (e põe um 0 no fim) ou -1 se der errado
static int _esmeB64Decodificar(const char* entrada, char* saida, size_t max) {
  size_t n = strlen(entrada), o = 0;
  uint32_t acc = 0; int bits = 0;
  for (size_t i = 0; i < n; i++) {
    if (entrada[i] == '=') break;
    int v = _esmeB64Valor(entrada[i]);
    if (v < 0) return -1;
    acc = (acc << 6) | (uint32_t)v; bits += 6;
    if (bits >= 8) {
      bits -= 8;
      if (o + 1 >= max) return -1;
      saida[o++] = (char)((acc >> bits) & 0xFF);
    }
  }
  saida[o] = 0;
  return (int)o;
}

// ---------------------------------------------------------------- Wi-Fi ----------
static void _esmeComecarWifi() {
  WiFi.persistent(false);                // quem guarda a rede somos nós (EEPROM)
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.disconnect();
  if (_esmeRede.senha[0]) WiFi.begin(_esmeRede.ssid, _esmeRede.senha);
  else                    WiFi.begin(_esmeRede.ssid);               // rede aberta
  IPAddress ip;
  if (ip.fromString(_esmeRede.ip)) { _esmeDestino = ip; _esmeTemDestino = true; }   // reserva, até chegar um aviso
}

// espera conectar; devolve 0 = conectou, ou o código do erro
static const char* _esmeEsperarWifi(unsigned long limiteMs) {
  unsigned long inicio = millis(), falhaDesde = 0;
  wl_status_t falha = WL_IDLE_STATUS;
  while (millis() - inicio < limiteMs) {
    wl_status_t s = WiFi.status();
    if (s == WL_CONNECTED) return 0;
    bool ehFalha = (s == WL_NO_SSID_AVAIL || s == WL_CONNECT_FAILED
#ifdef ESP8266
                    || s == WL_WRONG_PASSWORD
#endif
                   );
    if (ehFalha) {
      if (s != falha) { falha = s; falhaDesde = millis(); }
      if (millis() - falhaDesde > 4000UL) break;        // a falha se mantém: não adianta esperar mais
    } else {
      falha = WL_IDLE_STATUS;
    }
    delay(100);
  }
  if (WiFi.status() == WL_CONNECTED) return 0;
  if (falha == WL_NO_SSID_AVAIL) return "REDE_NAO_ENCONTRADA";
  if (falha == WL_CONNECT_FAILED
#ifdef ESP8266
      || falha == WL_WRONG_PASSWORD
#endif
     ) return "SENHA_INCORRETA";
  return "TEMPO_ESGOTADO";
}

// ---------------------------------------------------------------- comandos pela USB ----------
static char _esmeLinha[256];
static size_t _esmeTam = 0;
static bool _esmeEstourou = false;

static void _esmeResponder(const char* texto) { Serial.println(texto); }

static void _esmeTratarCFG(char* linha) {
  // CFG;<versao>;<ssid_b64>;<senha_b64>;<ip>
  char* campos[5]; int n = 0;
  for (char* p = linha; n < 5; ) {
    campos[n++] = p;
    char* ponto = strchr(p, ';');
    if (!ponto) break;
    *ponto = 0; p = ponto + 1;
  }
  if (n != 5 || strcmp(campos[1], "1") != 0) { _esmeResponder("ERRO;COMANDO_INVALIDO"); return; }

  EsmeRede nova; memset(&nova, 0, sizeof(nova));
  int ls = _esmeB64Decodificar(campos[2], nova.ssid, sizeof(nova.ssid));
  int lp = _esmeB64Decodificar(campos[3], nova.senha, sizeof(nova.senha));
  IPAddress ip;
  if (ls < 1 || ls > 32 || lp < 0 || lp > 63 || (lp > 0 && lp < 8) || strlen(campos[4]) > 15 || !ip.fromString(campos[4])) {
    _esmeResponder("ERRO;COMANDO_INVALIDO"); return;
  }
  strncpy(nova.ip, campos[4], sizeof(nova.ip) - 1);

  // Só guarda na memória DEPOIS de conseguir conectar: um erro de digitação não apaga a rede que já funcionava.
  EsmeRede anterior = _esmeRede;
  bool tinhaAnterior = _esmeTemRede;
  _esmeRede = nova;
  _esmeTemRede = true;
  _esmeComecarWifi();
  const char* erro = _esmeEsperarWifi(ESME_TEMPO_WIFI_MS);
  if (erro) {
    _esmeRede = anterior; _esmeTemRede = tinhaAnterior;
    if (tinhaAnterior) _esmeComecarWifi(); else WiFi.disconnect();
    Serial.print("ERRO;"); Serial.println(erro);
    return;
  }
  if (!_esmeGravarRede()) { _esmeResponder("ERRO;FLASH"); return; }
  Serial.print("OK;WIFI;"); Serial.println(WiFi.localIP());
}

static void _esmeTratarLinha(char* linha) {
  size_t n = strlen(linha);
  while (n > 0 && (linha[n - 1] == '\r' || linha[n - 1] == ' ')) linha[--n] = 0;
  if (strcmp(linha, "ESME?") == 0) {
    Serial.print("ESME;"); Serial.print(ESME_TIPO); Serial.print(";"); Serial.println(ESME_VERSAO);
  } else if (strncmp(linha, "CFG;", 4) == 0) {
    _esmeTratarCFG(linha);
  }
  // outras linhas (ex.: lixo, o que o monitor serial digitar) são ignoradas
}

static void _esmeLerSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      if (_esmeEstourou) { _esmeResponder("ERRO;COMANDO_INVALIDO"); }
      else { _esmeLinha[_esmeTam] = 0; _esmeTratarLinha(_esmeLinha); }
      _esmeTam = 0; _esmeEstourou = false;
    } else if (_esmeTam < sizeof(_esmeLinha) - 1) {
      _esmeLinha[_esmeTam++] = c;
    } else {
      _esmeEstourou = true;
    }
  }
}

// ---------------------------------------------------------------- aviso do IP do notebook ----------
static void _esmeOuvirAnuncio() {
  if (WiFi.status() != WL_CONNECTED) { _esmeEscutando = false; return; }
  if (!_esmeEscutando) { _esmeUdpAnuncio.begin(ESME_PORTA_ANUNCIO); _esmeEscutando = true; }
  int tam = _esmeUdpAnuncio.parsePacket();
  while (tam > 0) {
    char buf[64];
    int n = _esmeUdpAnuncio.read(buf, sizeof(buf) - 1);
    if (n > 0) {
      buf[n] = 0;
      // ESME-IP;1;<ip>;<porta_mesa>;<porta_batedor>
      if (strncmp(buf, "ESME-IP;1;", 10) == 0) {
        IPAddress origem = _esmeUdpAnuncio.remoteIP();          // quem avisou é o destino (escopo 14.1)
        char* p = buf + 10;
        char* ponto = strchr(p, ';');
        if (ponto) {
          char* pm = ponto + 1;
          char* ponto2 = strchr(pm, ';');
          if (ponto2) {
            *ponto2 = 0;
            long portaMesa = atol(pm), portaBatedor = atol(ponto2 + 1);
            long porta = (strcmp(ESME_TIPO, "MESA") == 0) ? portaMesa : portaBatedor;
            if (porta > 0 && porta < 65536) _esmePorta = (uint16_t)porta;
          }
        }
        _esmeDestino = origem; _esmeTemDestino = true; _esmeUltimoAnuncio = millis();
      }
    }
    tam = _esmeUdpAnuncio.parsePacket();
  }
}

static void _esmeManterWifi() {
  if (!_esmeTemRede) return;
  if (WiFi.status() == WL_CONNECTED) { _esmeSemWifiDesde = 0; return; }
  if (_esmeSemWifiDesde == 0) _esmeSemWifiDesde = millis();
  if (millis() - _esmeSemWifiDesde > ESME_REGRAVAR_WIFI_MS) {          // o reconectar automático não resolveu
    _esmeSemWifiDesde = millis();
    if (_esmeRede.senha[0]) WiFi.begin(_esmeRede.ssid, _esmeRede.senha);
    else                    WiFi.begin(_esmeRede.ssid);
  }
}

// ---------------------------------------------------------------- uso pelo sketch ----------
inline void esmeIniciar() {
  EEPROM.begin(sizeof(EsmeRede) + 8);
  _esmeTemRede = _esmeLerRede();
  if (_esmeTemRede) _esmeComecarWifi();       // sem esperar: o resto do programa segue
}

inline void esmeServico() {
  _esmeLerSerial();
  unsigned long agora = millis();
  if (agora - _esmeUltimaChecagem >= 20) {    // Wi-Fi e aviso: a cada 20 ms basta
    _esmeUltimaChecagem = agora;
    _esmeManterWifi();
    _esmeOuvirAnuncio();
  }
}

// espera `ms` sem deixar de atender a USB e o Wi-Fi (no lugar de delay() em esperas longas)
inline void esmeEsperar(unsigned long ms) {
  unsigned long inicio = millis();
  while (millis() - inicio < ms) { esmeServico(); delay(1); }
}

inline bool esmeConectado() { return WiFi.status() == WL_CONNECTED; }
inline bool esmePodeEnviar() { return _esmeTemDestino && WiFi.status() == WL_CONNECTED; }

// manda um pacote UDP ao notebook (devolve false se ainda não há Wi-Fi ou destino)
inline bool esmeEnviar(const uint8_t* dados, size_t tamanho) {
  if (!esmePodeEnviar()) return false;
  if (!_esmeUdpEnvio.beginPacket(_esmeDestino, _esmePorta)) return false;
  _esmeUdpEnvio.write(dados, tamanho);
  return _esmeUdpEnvio.endPacket() == 1;
}