# Etiqueta - NS

Lê iPads / iPhones ligados por USB e imprime uma etiqueta **60 × 40 mm** com o
número de série (código de barras Code 128), a saúde e os ciclos da bateria.
Roda 100 % na máquina (servidor local em `http://localhost:8765`).

## Baixar e instalar

**Não clone este repositório para usar.** Baixe o pacote pronto:

➡️ **[Releases](../../releases/latest)** → `Etiqueta-NS.zip`

Descompacte numa pasta fixa e dê dois cliques em `INSTALAR.bat`.
Guia completo: **https://claude.ai/code/artifact/6bd42bca-1c65-4154-9dc6-45a04e9a580f**

Requisitos: Windows 10/11, **3uTools** (ou iTunes / Apple Devices) para o driver
USB da Apple, e Python 3 (o `INSTALAR.bat` instala se faltar).

## Como funciona

| Peça | O quê |
|---|---|
| `server.py` | servidor HTTP, só biblioteca padrão do Python 3 |
| `static/` | interface (grade de 10 caixas, engrenagem de ajustes) |
| `raw_print.ps1` | envia o comando cru (EPL2 / ZPL) ao spooler da impressora |
| `vendor/libimobile/` | binários [libimobiledevice](https://github.com/libimobiledevice-win32) — **só no `.zip` da release** |
| `config.json` | ajustes locais (criado no primeiro uso; fora do versionamento) |

Leitura dos aparelhos: `ideviceinfo` + `idevicediagnostics`. Impressão: EPL2 por
padrão (`language: "auto"` adivinha EPL/ZPL pela impressora).

## Desenvolvimento

Para rodar a partir do código, baixe o `vendor/libimobile/` do `.zip` da release
(ou dos binários do projeto libimobiledevice-win32) e coloque em `vendor/`.
Depois: `python server.py`.
