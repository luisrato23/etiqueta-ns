# Etiqueta - NS — 60 × 40 mm

Etiqueta:

```
      MODELO 64 GB | Cor
     [  código de barras  ]
        Nº DE SÉRIE (texto)
   BT 88%   CC 141
```

Tudo centralizado, em pilha. Imprime direto na **ELGIN L42PRO FULL**
(EPL, com opção de ZPL).

- **Nome do modelo**: tabela `ProductType → nome` em `server.py`
  (`MODEL_NAMES`); fora da tabela usa o `MarketingName` do próprio iPad,
  senão o código Apple (`iPad7,11`).
- **Memória**: `TotalDiskCapacity` do aparelho, arredondada pro tamanho
  comercial (32 GB, 128 GB, 1 TB…). Vai junto do nome do modelo.
- **Cor**: vem do código `DeviceColor` do aparelho (ex.: `2`). O nome
  ("Prata", "Cinza-espacial"…) é uma **aproximação** — a Apple não manda o
  nome por USB, só um número. Se algum aparelho mostrar a cor errada, use
  **Ver comando** para achar o código e corrija em `config.json` → `color_names`.

A interface é uma grade de **10 caixas** (tema claro). Sem prévia da etiqueta —
o que sai na impressora é o desenho acima.

**Cor da caixa:** 🔴 vermelha = lendo o aparelho · 🟢 verde = leitura concluída ·
🟠 laranja = precisa tocar em "Confiar" no aparelho. **Reler agora** deixa tudo
vermelho de novo enquanto relê.

## Como usar (dia a dia)

O servidor **liga sozinho quando o Windows inicia** (em segundo plano, sem
janela). O link é sempre o mesmo:

> **http://localhost:8765**  — atalho **"Etiquetas de iPad"** na área de trabalho.

Fixe essa aba no navegador (botão direito na aba → *Fixar*) e ela fica lá.

1. Ligue os iPads no cabo USB — dá para vários ao mesmo tempo com um hub.
   A tela tem **10 caixas**; cada aparelho conectado ocupa uma.
2. Na 1ª vez o iPad pede **"Confiar neste computador"** — desbloqueie e toque
   em **Confiar** (se a caixa pedir, clique em **Parear / Confiar**).
3. Imprimir:
   - **uma etiqueta**: botão **Imprimir esta** dentro da caixa;
   - **algumas**: clique nas caixas que quer (ficam marcadas) e
     **Imprimir selecionadas (N)**;
   - **todas de uma vez**: **Imprimir todas conectadas (N)**.
   O campo **cópias** vale para todas as etiquetas do lote.

### Ligar / desligar / manual

| Ação | Como |
|---|---|
| Está sempre ligado? | Abra http://localhost:8765 — se abrir, está no ar. |
| Parar o servidor | dois cliques em `PARAR.bat` |
| Ligar de novo na hora | dois cliques em `INICIAR.bat` (abre com janela e log visível) ou `iniciar_oculto.vbs` (sem janela) |
| Tirar da inicialização | apague `Etiquetas de iPad.vbs` da pasta *Inicializar* do Windows (tecle Win+R, `shell:startup`) |
| Ver o que aconteceu | arquivo `server.log` na pasta do projeto |

O driver USB da Apple (*Apple Mobile Device Support*) já está instalado nesta
máquina. Se trocar de PC, instale o **Apple Devices** (Microsoft Store) ou o iTunes.

## De onde vêm os dados

| Dado | Fonte |
|---|---|
| Nº de série, modelo, iPadOS | `ideviceinfo` (lockdown) |
| Carga atual (%) | `ideviceinfo -q com.apple.mobile.battery` |
| Saúde da bateria (%) e ciclos | `idevicediagnostics` (interface de diagnóstico) |

Testado com um iPhone em iOS 26.5: saúde (92%) e ciclos (490) vieram certos pelo
comando `idevicediagnostics ioregentry AppleSmartBattery`. Em alguns aparelhos
mais fechados isso pode sair como **`N/D`** — nesse caso a etiqueta imprime com o
nº de série normalmente e "N/D" nos outros campos. Para ver o que um aparelho
específico devolveu, abra:

```
http://localhost:8765/api/debug?udid=SEU_UDID
```

o campo `raw_diag` mostra a resposta crua de cada comando testado.

## Ajustes — `config.json`

| Campo | Para quê |
|---|---|
| `printer_name` | Nome exato da impressora no Windows (Painel de Controle > Dispositivos). |
| `label.language` | `"epl"` (padrão, driver ELGIN) ou `"zpl"`. |
| `label.dpmm` | Resolução: **8** = 203 dpi (L42 Pro é 203). |
| `label.gap_dots` | Espaço entre etiquetas em pontos (~24 = 3 mm). |
| `label.offset_x` / `offset_y` | Deslocamento de tudo (pontos). Use os botões da tela. |
| `label.darkness` | Escurecimento (0–15 no EPL). Aumente se sair fraco. |
| `label.print_speed` | Velocidade (1–4). Diminua se sair borrado. |
| `label.element_scale` | **Tamanho geral de tudo.** `1.0` = 100 %, `0.8` = 80 % (padrão), `0.9` = 90 %… |
| `label.show_color` | `true` mostra ` | Cor` na linha de cima; `false` só o modelo. |
| `label.bottom_labels` | `true` = "BT 88%  CC 141"; `false` = só "88%  141". |
| `label.flip_180` | `true` = gira a etiqueta 180° (EPL `ZB` / ZPL `^POI`). Também tem caixa **girar 180°** em *Ajustes*. |
| `label.text_bold` | `false` (padrão) = letras mais finas (fonte EPL menor). `true` = fonte grossa. Caixa **negrito** em *Ajustes*. |
| `label.darkness` | `0`–`15`. Baixe (ex.: 6–8) se as letras/barras saírem grossas ou borradas. Campo **escuro** em *Ajustes*. |
| `label.barcode_module` | Largura da barra fina (2 recomendado). Baixe p/ 1 se não couber. |
| `label.barcode_height` | Altura-base do código (é multiplicada pelo `element_scale`). |
| `label.barcode_x` | Ausente = centraliza sozinho. Número = posição fixa. |
| `label.strip_accents` | `true` tira acentos (fonte da ELGIN não tem todos). |
| `color_names` | Corrige o nome da cor por código. Ex.: `{"2": "Prata", "5": ["Cinza-espacial", "#555"]}` |
| `diagnostics_commands` | Comandos tentados para achar saúde/ciclos. |

O resto do layout (posição do modelo, da cor, dos números) é calculado
automaticamente a partir do `element_scale` — não precisa mexer.

Depois de editar, feche e reabra o `INICIAR.bat`.

### Calibração da etiqueta (FAÇA UMA VEZ)

Se sair **etiqueta em branco**, pular etiqueta, ou cortar a impressão:

1. Impressora **ligada**, tampa fechada, rolo 60×40 carregado.
2. Segure o botão **FEED** por ~4 s e solte. Ela alimenta algumas etiquetas
   medindo o espaço entre elas (sensor de gap) e para. Pronto.
3. Volte no navegador e clique em **Etiqueta de teste** — deve sair uma moldura
   com uma cruz no centro, encaixada na etiqueta.

### Idioma da impressora — EPL x ZPL

A L42 Pro Full aceita os dois. O driver instalado aqui é **EPL**, então o padrão
é `"language": "epl"`. Se preferir ZPL (ou se o EPL sair torto), troque no seletor
**idioma** da tela, ou em `config.json` (`"language": "zpl"`), e clique
**Etiqueta de teste** de novo.

### Ajuste fino da posição

Na barra do topo, **← →** e **↑ ↓** deslocam tudo em pontos (8 pontos = 1 mm).
Clique **Aplicar**, imprima **Etiqueta de teste**, repita até a moldura encaixar.
Fica salvo em `config.json` (`offset_x` / `offset_y`).

## Peças do projeto

```
INICIAR.bat            inicia tudo
server.py              servidor local (Python, sem dependências externas)
raw_print.ps1          envia o ZPL cru para o spooler da impressora
config.json            ajustes
static/                interface do navegador
vendor/libimobile/     binários libimobiledevice (leitura dos iPads)
static/vendor/         JsBarcode (preview do código de barras na tela)
_last_label.zpl        última etiqueta gerada (para depuração)
```

## Requisitos

- **Python 3** no PATH (já instalado: 3.14).
- Driver USB da Apple (Apple Devices / iTunes).
- Impressora instalada no Windows com o nome de `config.json`.
