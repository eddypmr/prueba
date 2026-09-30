# One Piece EB-05 Stock Monitor

Monitor automático ejecutado con GitHub Actions cada 30 minutos.

## Qué vigila

### Fichas directas
- Garhis
- Kaburi
- Gameria

### Descubrimiento de nueva ficha/listado
- inGenio BCN Games
- Metrópolis Center
- Mathom
- Zacatrus
- Paper Dealer

Metrópolis Center se comprueba con Chromium + Playwright. Las demás tiendas intentan HTTP normal y, si falla, usan Playwright como fallback.

## Frecuencia

El workflow corre en los minutos **07 y 37 de cada hora**:

```
7,37 * * * *
```

También puede ejecutarse manualmente desde:

**Actions → EB-05 Stock Monitor → Run workflow**

## Telegram

El monitor funciona sin Telegram, pero para recibir avisos hay que crear estos dos Repository Secrets:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Ruta en GitHub:

**Settings → Secrets and variables → Actions → New repository secret**

No pongas nunca el token directamente en `monitor.py`.

### Obtener TELEGRAM_BOT_TOKEN

1. Abre Telegram.
2. Habla con **@BotFather**.
3. Ejecuta `/newbot`.
4. Sigue los pasos.
5. BotFather te dará el token.

### Obtener TELEGRAM_CHAT_ID

1. Abre el bot que acabas de crear y pulsa **Start**.
2. Envíale cualquier mensaje, por ejemplo `hola`.
3. Abre en el navegador:

```
https://api.telegram.org/botTU_TOKEN/getUpdates
```

4. Busca algo parecido a:

```json
"chat": {
  "id": 123456789
}
```

Ese número es `TELEGRAM_CHAT_ID`.

## Cómo funcionan los avisos

La primera ejecución crea una línea base y **no envía alertas**.

Después avisa cuando ocurre alguno de estos cambios:

- `NO_DISPONIBLE → DISPONIBLE`
- `NO_DISPONIBLE → POSIBLE_STOCK`
- `BUSCANDO → EB05_ENCONTRADO`

Así evita mandar el mismo aviso cada 30 minutos.

## Estado

`state.json` guarda el último estado de cada tienda. GitHub Actions solo hace commit cuando cambia.

Los secretos de Telegram no se guardan en ese archivo.


## Informe de estado cada 12 horas

Además de las alertas inmediatas de stock, el monitor envía por Telegram un parte de salud cada 12 horas.

El informe indica:

- cuántas tiendas han respondido correctamente en la última pasada;
- el estado actual de cada ficha/catálogo;
- si una web está bloqueando al runner, devuelve captcha o no responde;
- qué comprobaciones usan HTTP normal y cuáles usan Playwright/Chromium.

La primera ejecución tras activar esta función envía un informe inmediatamente. Después se guarda `_meta.last_status_report` en `state.json` y no se vuelve a enviar hasta que hayan pasado 12 horas.

Si Telegram falla al enviar el parte, el monitor no marca el informe como entregado y vuelve a intentarlo en la siguiente ejecución de 30 minutos.


## Gameria: fallback mediante ScraperAPI

Gameria bloquea actualmente las conexiones directas procedentes de GitHub Actions y también devuelve 403 a Jina Reader.

El monitor tiene un último fallback opcional mediante ScraperAPI. Para activarlo, crea este Repository Secret:

`SCRAPERAPI_KEY`

Ruta:

**Settings → Secrets and variables → Actions → New repository secret**

El código prueba ScraperAPI sin JavaScript rendering ni proxy premium para minimizar el consumo de créditos.
