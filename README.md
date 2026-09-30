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
