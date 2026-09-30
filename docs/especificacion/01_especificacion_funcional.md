# 1. Especificación funcional — Agente Interno de Control de Negocio

**Versión:** 1.0 · **Fecha:** 30/9/2026 · **Estado:** validada en entrevista (fases 1–8)

## 1.1 Propósito
Asistente de solo lectura que conoce el estado interno de un comercio minorista cubano (tienda física + web),
lo analiza y se lo explica a su dueño por Telegram. Más adelante también informará a un Agente Orquestador.

## 1.2 Contexto del MVP
- Producto replicable para mipymes cubanas. Se demuestra con el negocio **MercadoAgentico**.
- 1 tienda física + 1 web con **stock compartido**. 150 productos (alimentos, aseo, farmacia, ferretería, electrodomésticos, energía, climatización, electrónica, movilidad).
- Precios fijos en **USD**, cobrados en **CUP** a la tasa diaria de **elTOQUE** (redondeo hacia arriba a 10 CUP). Pagos: efectivo USD, efectivo CUP, transferencia CUP (Transfermóvil/EnZona), pagos mixtos.
- Zona horaria: **America/Havana**. "Hoy" = fecha y hora actuales de La Habana.
- Único usuario: **el dueño**.

## 1.3 Responsabilidades
| # | Responsabilidad | Cómo |
|---|---|---|
| R1 | Consultar la BD del negocio | Solo mediante 12 herramientas de lectura (sin SQL libre) |
| R2 | Comprender el estado interno | Resumen del día, tendencias, comparación con periodos anteriores |
| R3 | Analizar productos, inventario, ventas, costes, precios, tasa | Métricas con definiciones únicas (ver 5. Reglas) |
| R4 | Detectar situaciones importantes | Reglas deterministas en `get_alerts` (agotados, riesgo de rotura, excesos, sin movimiento, margen bajo, devoluciones, anulaciones, caídas de venta, tasa, calidad de datos) |
| R5 | Responder preguntas del dueño | Texto libre + comandos en Telegram |
| R6 | Comunicarse por Telegram | Respuestas + resumen diario 19:30 + alertas urgentes |
| R7 | Informar al futuro orquestador | API interna `POST /v1/consulta` con salida JSON estructurada |

## 1.4 Fuera de alcance (v1)
- **Cualquier escritura**: modificar productos, precios, inventario; registrar ventas; eliminar datos; compras; operaciones económicas.
- Información de mercado o competencia (futuro Agente Externo).
- Beneficio neto (no hay gastos fijos registrados): solo beneficio **bruto**.
- Datos de clientes (no se registran).
- Caducidades y lotes (no se registran).
- Gráficos, notas de voz, imágenes.
- Grupos de Telegram y usuarios distintos del dueño.

## 1.5 Funciones para el dueño
1. **Preguntas en lenguaje natural** sobre ventas, productos, stock, rentabilidad, devoluciones, anulaciones y tasa.
2. **Comandos**: `/resumen`, `/ventas`, `/stock`, `/producto <nombre>`, `/alertas`, `/ayuda`.
3. **Botones de consulta** debajo de los mensajes (nunca botones de acción).
4. **Resumen diario** a las 19:30 (La Habana).
5. **Alertas urgentes** inmediatas: máx. 3/día, sin repetir en 24 h, silencio 21:00–8:00.
6. **Estimaciones** simples ("¿cuánto venderé en diciembre?"), siempre marcadas como inferencia 💡.

## 1.6 Clasificación de la información (obligatoria)
| Tipo | Significado | Marca en Telegram | `kind` en JSON |
|---|---|---|---|
| HECHO | Dato leído tal cual de la BD | sin marca | `fact` |
| CÁLCULO | Métrica derivada con una fórmula definida | 📊 | `calculation` |
| INFERENCIA | Interpretación, causa probable o estimación | 💡 | `inference` |
| NO DISPONIBLE | El dato no existe en la BD o está fuera de alcance | ❔ | `not_available` |

Toda respuesta indica el **periodo** y la **hora de los datos**.

## 1.7 Requisitos no funcionales
- Respuesta a Telegram < 15 s en consultas normales; orquestador < 30 s.
- Cada consulta a BD ≤ 10 s y con límite de filas.
- 30 consultas/hora por usuario.
- Registro de cada interacción (90 días).
- Idioma: español de Cuba, tuteo, sin tecnicismos.

## 1.8 Dependencias
- Supabase (PostgreSQL), proyecto MercadoMVP.
- API de elTOQUE (tasa diaria; la carga la hace el alimentador, no el agente).
- API de Claude (modelo del agente). Servidor fuera de Cuba.
- Bot de Telegram.
- Proceso **alimentador** diario que mantiene vivo el negocio de demostración (fuera del alcance del agente).

## 1.9 Pendiente de construir (siguientes pasos)
1. Esquema `agente` con las 12 funciones + rol de solo lectura (ver 3/4 y 6).
2. Servicio Python (bot + modelo + planificador + API interna + registro).
3. Alimentador diario (continuación del generador de `scripts/demo/`).
4. Ejecución de los casos de prueba (10).
