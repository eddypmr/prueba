# One Piece EB-05 Stock Monitor

Monitor de cajas inglesas precintadas EB-05 / OP-18. Cloudflare invoca GitHub Actions cada 30 minutos y el cron nativo de GitHub es un respaldo horario.

## Qué vigila

### Fichas directas
- Garhis
- Kaburi
- Gameria

### Descubrimiento de nueva ficha/listado
- inGenio BCN Games
- Mathom
- Zacatrus
- Paper Dealer

Metrópolis Center se revisa manualmente (ver la sección específica más abajo).

Metrópolis Center está excluida del scraping y se revisa manualmente. Las demás tiendas intentan HTTP normal y, si falla, pueden usar Playwright.

## Frecuencia

Cloudflare activa comprobaciones cada **30 minutos**. GitHub mantiene un cron de respaldo en el minuto 17 de cada hora (puede retrasarse):

```
17 * * * *
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
- [x] **Revisar periodicidad redundante de GitHub**. Cloudflare cada 30 minutos
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


## Validación de catálogos (fase 4)

- El monitor registra cuántas tarjetas reconocibles aparecen en cada página.
- Un catálogo con productos visibles o mensaje explícito de catálogo vacío es
  verificable; una página que solo responde HTTP 200 o menciona One Piece
  **no** es suficiente.
- Si todas sus páginas carecen de productos reconocibles y de mensaje de vacío,
  la búsqueda aparece como **no verificable**, sin modificar el estado de stock
  anterior ni generar avisos falsos.
- Validado en GitHub Actions #993 (diagnóstico) y #994 (protección), con
  33 pruebas automáticas correctas.
- **Metrópolis Center:** actualmente responde sin tarjetas reconocibles
  desde el runner. Requiere revisión del HTML/DOM de esa tienda; no se considera
  una búsqueda de catálogo confirmada. Se mantienen los estados existentes.

## Alertas persistentes (fase 3)

Las alertas importantes de EB-05 y OP-18, incluidos nuevos listados, se guardan
primero en `state.json` bajo `_outbox`, cada una con ID de transición único.
El workflow confirma el commit de ese estado **antes** de hacer la petición a
Telegram. Solo cuando Telegram devuelve HTTP 200 y JSON `ok: true` se marca
`sent_at` y se confirma el acuse en un segundo commit.

Ante timeout, fallo HTTP, límite 429 o error de Telegram, el aviso no se marca
como entregado. Se reintenta en una ejecución posterior (sin saturar la API).
Los informes cada 12 horas pasan también por la cola. El test manual de Telegram
continúa siendo un envío de prueba directo.

**Límite:** un aviso puede repetirse si Telegram lo entrega pero se pierde el
acuse antes de guardarse en GitHub (semántica *al menos una vez*). No se puede
garantizar entrega si GitHub permanece inaccesible o si la detección del stock
falla por bloqueo de la tienda.

Las pruebas `tests/test_notification_outbox.py` verifican reintentos, fusión de
estados, ausencia de duplicados en la cola y tratamiento de errores.


### Metrópolis Center: revisión manual

Se intentó comprobar el catálogo mediante Playwright y también mediante HTTP
convencional. En GitHub Actions la consulta HTTP devolvió **403** y Chromium
mostró una página sin tarjetas verificables (ejecución #996, 2026-10-19).

De acuerdo con la preferencia del usuario, **Metrópolis Center queda fuera de
las comprobaciones programadas de EB-05 y OP-18**. Los últimos estados
históricos de `state.json` se conservan sin modificación, pero ya no se
consideran comprobaciones actuales. Se revisará manualmente la tienda en:
https://metropolis-center.com/es/catalogo/juegos-de-cartas/one-piece

Las demás tiendas, pruebas automáticas y avisos de Telegram siguen activos.


## Guardas para cajas inglesas y tiendas candidatas (27/10/2026)

- La detección en catálogos exige referencias de **EB-05 u OP-18**, idioma **inglés** y formato **Booster Box / Display**. Rechaza japonés, singles, cases, displays de 12 y desprecintados; cuando no hay pruebas suficientes de identidad, **no afirma disponibilidad**.
- En fichas individuales, `PREORDER` o `Disponibilidad: RESERVA` prevalece sobre textos como «En stock» o botones de compra. El estado `PREVENTA` **no emite alertas de stock inmediato**.
- **Turol Games** (EB-05 y OP-18) y **Bandua Wargames** (EB-05) quedan en **modo diagnóstico de solo lectura**. Se han probado sus fichas por HTTP sin modificar `state.json` ni Telegram. **Turol EB-05 y OP-18 quedaron pausados** porque GitHub devolvió HTTP 202; no se repite la petición bloqueada cada 30 minutos. **Bandua EB-05 continúa en diagnóstico**, devolviendo `PREVENTA` por su etiqueta PREORDER aunque aparezca «En stock». Requieren validación adicional antes de activar notificaciones.
- Las páginas candidatas pueden mostrar todas las etiquetas de disponibilidad a la vez (Turol) o «PREORDER» + «En stock» (Bandua). No interpretar esas palabras aisladas como stock confirmado.
- Para habilitar estas tiendas como alertas reales: verificar HTML servido al runner, identificar elementos de disponibilidad específicos, añadir casos de prueba y validar las transiciones reales; **no hacerlo simplemente copiando sus URL a `DIRECT_PRODUCTS`**.


## LOGPOSE: comparador español (EB-05 y OP-18)

El bot consulta `https://tcglogpose.com/buscar?setCode=EB-05` y `https://tcglogpose.com/buscar?setCode=OP-18` como **fuente de diagnóstico adicional**. Solo busca Booster Boxes en inglés, excluyendo sobres, cajas japonesas y cases. La palabra «Disponible» del comparador **no confirma stock inmediato**: puede incluir preventas y los datos se actualizan varias veces al día.

Las consultas a LOGPOSE se registran como `LOGPOSE_EB05` y `LOGPOSE_OP18` en el log. Si el HTML no permite reconocer de forma fiable la caja, se declara **no verificable** y no se inventa disponibilidad. De momento no genera avisos en Telegram ni modifica `state.json`. Para seguir otros sets (por ejemplo, OP-19), añadir la referencia a `WATCHED_SETS` en `logpose_sources.py` y verificar los resultados reales.

En la primera ejecución real se comprobó que LOGPOSE devuelve enlaces de distintas variantes con etiquetas cercanas. Por seguridad, se limita a las fichas de **Booster Box EN** `/producto/429` (EB-05) y `/producto/453` (OP-18), y no utiliza la etiqueta de disponibilidad de su catálogo como confirmación de stock.


## HeroFreaks (Almàssera, Valencia) — 29/10/2026

Se comprueban **EB-05** y **OP-18** en las páginas de One Piece y Próximamente de `herofreaks.com`. Se buscan solamente enlaces de la ficha de **Booster Display**, y después se verifica el detalle del producto: referencia del set, idioma inglés (atributos WooCommerce) y botón de compra habilitado en la ficha. Las preventas, sobres individuales, productos japoneses, estados ambiguos y páginas inaccesibles **no generan alertas**. La primera confirmación de compra real en una caja inglesa sí avisa por Telegram con un enlace directo. El estado se guarda como `HEROFREAKS` y `OP18_HEROFREAKS` en `state.json` y aparece en los informes periódicos. El precio publicado de EB-05 a finales de octubre era 154,95 €, pero no confirma disponibilidad.
