# One Piece EB-05 Stock Monitor

Monitor automático ejecutado con GitHub Actions con intentos cada 15 minutos para compensar retrasos o ejecuciones omitidas del scheduler.

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

El workflow intenta correr en los minutos **07, 22, 37 y 52 de cada hora**:

```
7,22,37,52 * * * *
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


## Plan de mejoras acordado (octubre de 2026)

Orden de trabajo: validar una fase en GitHub Actions antes de comenzar la siguiente.

- [x] **Fase 1 — Catálogos compartidos EB-05 / OP-18**. Una sola descarga,
  validación y paginación por tienda y ejecución; dos detectores independientes
  sobre el mismo HTML. Validado en la ejecución #777 (2026-10-15).
- [x] **Fase 2 — Disponibilidad JSON-LD vinculada al producto correcto**.
  Se interpretan objetos `Product` y sus `offers` solo si nombre, URL,
  SKU o identificador corresponden a EB-05 u OP-18. JSON malformado,
  productos recomendados, estados ambiguos y preventas no generan
  disponibilidad confirmada. Validada con 12 pruebas automáticas y en
  la ejecución #826 (2026-10-16).
- [ ] **Refactor configurable por producto**. Eliminar la duplicación restante
  entre EB-05 y OP-18 para añadir nuevos sets sin copiar funciones.
- [ ] **Revisar periodicidad redundante de GitHub**. Cloudflare cada 30 minutos
  como principal y cron nativo con menor frecuencia como respaldo.
- [ ] **Evaluar consulta de Gameria desde Cloudflare**. Solo si ese origen puede
  acceder a la tienda; no intentar saltarse controles ni reiterar peticiones bloqueadas.
- [ ] **Alertas opcionales de precio**. Umbrales configurables y solo avisar de
  stock confirmado a precio interesante.

La fase 1 no modifica la estrategia de fichas directas, los avisos de Telegram
ni la persistencia de `state.json`. La fase 2 se tratará como un cambio separado
para poder validar los falsos positivos de disponibilidad por separado.

### Validación automatizada de JSON-LD

Las 12 pruebas de `tests/test_jsonld_stock.py` se ejecutan antes de cada
monitorización con `python -m unittest discover -s tests -v`.
Si fallan, GitHub Actions detiene esa ejecución antes del scraping; si pasan,
el monitor continúa comprobando las tiendas con normalidad.
