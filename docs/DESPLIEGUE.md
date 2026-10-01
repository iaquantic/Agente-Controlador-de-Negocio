# Puesta en marcha del Agente Interno

Tiempo estimado: 20–30 minutos. Ninguna clave se escribe en el repositorio ni se envía por chat: todas van en el archivo `.env` del servidor.

## 1. Crear el bot de Telegram (5 min)
1. En Telegram, abre **@BotFather** → `/newbot` → elige nombre y usuario (p. ej. `MercadoAgenticoBot`). Te dará el **token**.
2. En @BotFather: `/setjoingroups` → elige el bot → **Disable** (el bot no se puede añadir a grupos).
3. Abre **@userinfobot** y escribe cualquier cosa: te responde tu **ID numérico** (`TELEGRAM_OWNER_ID`).
4. Opcional: `/setcommands` y pega:
   ```
   resumen - Cómo va el negocio hoy
   ventas - Ventas de hoy, semana o mes
   stock - Agotados y stock bajo
   producto - Ficha de un producto
   alertas - Alertas activas
   ayuda - Qué puedo preguntar
   ```

## 2. Activar los usuarios de la base de datos (5 min)
Los roles `agente_lectura` y `agente_registro` ya existen en MercadoMVP **sin contraseña ni acceso**.
En Supabase → **SQL Editor**, ejecuta (con contraseñas largas inventadas por ti):
```sql
alter role agente_lectura  with login password 'UNA-CONTRASEÑA-LARGA-1';
alter role agente_registro with login password 'UNA-CONTRASEÑA-LARGA-2';
```
Después, en **Connect → Session pooler**, copia la cadena de conexión y cambia el usuario por
`agente_lectura.btnkzxrkrqsgcuuxqtjd` (y `agente_registro.btnkzxrkrqsgcuuxqtjd` para el registro).

## 3. Clave de Claude
En https://console.anthropic.com → API Keys → crea una clave para este servicio.

## 4. Servidor
Requisitos: un VPS **fuera de Cuba** (la API de Claude no está disponible desde Cuba) con Python 3.11+ o Docker.

```bash
git clone <este repositorio> && cd Agente-Controlador-de-Negocio
cp .env.example .env && nano .env        # rellena TELEGRAM_*, ANTHROPIC_API_KEY, DB_URL_*

# Opción A: Python
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m agente_interno

# Opción B: Docker
docker build -t agente-interno . && docker run -d --restart unless-stopped --env-file .env --name agente agente-interno
```
En el arranque verás `Bot de Telegram en marcha`. Escríbele `/start` al bot desde tu cuenta.

### Modo demo
Los datos de MercadoAgentico terminan el **30/9/2026 a las 11:30**. Hasta que exista el alimentador diario,
deja `AGENTE_AHORA_FIJA=2026-09-30T11:30:00-04:00` en el `.env`: el agente se comporta como si fuera ese momento
(el resumen diario y las alertas se programan igual con la hora real del servidor). Cuando el alimentador esté
en marcha, borra esa línea.

## 5. Comprobar
- `/start`, `/resumen`, `/stock`, `/producto aceite`, "¿Hay algo raro que deba saber?".
- Desde otra cuenta de Telegram, escribe al bot: debe responder "Este asistente es privado…".
- Registro: tabla `registro.interacciones` en Supabase (o `registro/registro.jsonl` si no configuraste `DB_URL_REGISTRO`).

## 6. Pruebas automáticas
Ver `tests/README.md`. La batería conversacional (bloque B) se lanza con:
```bash
ANTHROPIC_API_KEY=... TEST_DB_URL_AGENTE="<cadena de agente_lectura>" .venv/bin/pytest -m llm -s
```
(coste aproximado: unas 17 conversaciones con Claude).

## Problemas frecuentes
| Síntoma | Causa probable |
|---|---|
| `password authentication failed` | Falta el paso 2 o el usuario no lleva `.btnkzxrkrqsgcuuxqtjd` |
| El bot no responde | Token incorrecto, o `TELEGRAM_OWNER_ID` no es tu ID numérico |
| "Ahora mismo no puedo consultar los datos" | Sin conexión a Supabase o clave de Claude no válida (mira el log del servidor) |
| "Hoy no has vendido nada" | Falta `AGENTE_AHORA_FIJA` (modo demo) mientras no hay alimentador |
