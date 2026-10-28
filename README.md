# ESME — Estimulador SomatoMotor Eletromagnético

Projeto de PBL do **Grupo 3 (T3)** de Engenharia Biomédica do Einstein, 4º semestre.

O ESME é um **air hockey adaptado para a reabilitação** de pessoas com sequelas nos membros superiores após um AVC. O paciente empurra o disco com um batedor sem fio; a **mesa** (ESP32, 8 bobinas + gol) e o **batedor** (ESP8266 + MPU-6050) medem o movimento, e este **site local** mostra para a terapeuta dois indicadores de apoio por tentativa: **alcance** e **fluidez**.

> Os indicadores são de apoio e **não têm validação clínica**. Não substituem a avaliação da terapeuta.
>
> **Estado:** o site funciona e foi testado com dados simulados. O firmware ainda precisa ser testado nas placas reais. Veja `Escopo_PBL.md` (seção 0) para o que está pronto e o que falta.

## O que o site faz
- Login por lista de nomes (cada terapeuta vê só as sessões dos próprios pacientes; a supervisora vê todas).
- Nova sessão com TCLE virtual (sem o TCLE, a sessão é **anônima** e não é salva).
- Sessão ao vivo com alcance e fluidez por tentativa, Anular/Desfazer, comentário e curva de velocidade.
- Histórico, relatório para "Salvar como PDF" e CSV.
- Configurações: grava o Wi-Fi nas placas pelo USB.
- Equipe (só supervisora): criar, desativar e excluir perfis.
- Sobre nós: quem somos, termos de uso e como ler os indicadores.

## Como rodar (Windows)
Requisitos: Python 3.12 (Anaconda ou similar).

```
conda create -n siteESME python=3.12
conda activate siteESME
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Abra `http://127.0.0.1:8000/admin`, entre com o superusuário e crie o perfil da **supervisora** em *Fisioterapeutas* (papel **Super fisioterapeuta**). Depois use `http://127.0.0.1:8000` e crie as outras terapeutas pela página **Equipe**.

Para testar sem as placas, deixe o servidor rodando e, em outro terminal, use `python tools/simular_placas.py`. Em `core/settings.py`, `ESME_EXIGIR_CONFIGURACAO = False` libera a Nova sessão sem configurar as placas (só para testes).

## Dados e privacidade
- Tudo fica **só no notebook**: nada vai para a nuvem e o site atende só `127.0.0.1`.
- O nome do paciente e o comentário são **criptografados**; as listas mostram um código (`P-XXXXXX`).
- As chaves ficam em `dados_privados/`. Essa pasta e o `db.sqlite3` **não vão para o Git** (estão no `.gitignore`). **Faça backup das duas chaves** em lugar separado: sem elas, os nomes não abrem.
- Nunca suba chaves, banco de dados ou senhas para o repositório. Se isso acontecer, troque as chaves.

## Rede e firewall
As placas só conectam em Wi-Fi de **2,4 GHz**. Libere no firewall do Windows (inclusive em rede pública) as portas **UDP 4200, 4210 e 4212**. Rode **um** processo só do servidor: o estado das sessões fica na memória.

## Estrutura
```
core/         configurações do Django
terapia/      app (models, views, estado, receptor, fluidez, equipe, exportar...)
templates/    páginas HTML
firmware/     mesa_esme/ (ESP32) e batedor_esme/ (ESP8266), cada um com esme_config.h
tools/        simular_placas.py, diagnostico.py
Escopo_PBL.md        decisões e estado do projeto
protocolo-serial.md  protocolo para gravar o Wi-Fi nas placas
```

## Equipe
Grupo 3 · T3 · Engenharia Biomédica · Einstein.