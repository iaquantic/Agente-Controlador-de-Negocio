# Casos reales de uso (fase 6, validados)

Base de la batería de pruebas y del guion de demo.

## A. Ventas
1. ¿Cuánto vendí hoy?
2. ¿Cómo voy esta semana comparado con la pasada?
3. ¿Cuánto vendí en septiembre, en USD y en CUP?
4. ¿Qué pasó ayer? Vendí muy poco.
5. ¿Cuánto se vende por la web y cuánto en la tienda?
6. ¿Cuánto me pagan por transferencia y cuánto en efectivo?
7. ¿Cuál es mi ticket medio?

## B. Productos
8. ¿Qué producto estoy vendiendo más?
9. ¿Cuáles son los 10 productos que más dinero me dejan?
10. ¿Qué productos no se venden?
11. ¿Cómo va el aceite?
12. ¿Cuántos ventiladores de pedestal vendí este mes?

## C. Stock
13. ¿Qué productos tienen poco stock?
14. ¿Qué se me ha agotado?
15. ¿Qué tengo que reponer esta semana?
16. ¿Tengo mercancía parada? ¿Cuánto dinero tengo metido ahí?
17. ¿Cuántos días me dura la leche en polvo?

## D. Rentabilidad
18. ¿Cuánto gané este mes?
19. ¿Qué productos me dejan poco margen?
20. ¿Qué categoría es la más rentable?
21. ¿Cómo me afecta la subida del dólar?

## E. Problemas y alertas
22. ¿Hay algo raro que deba saber?
23. ¿Por qué hay tantas ventas anuladas esta semana?
24. ¿Qué producto me están devolviendo mucho?

## F. Fuera de alcance
25. "Súbele el precio al café a 5 USD" → no lo hace; es de solo lectura.
26. "¿A cuánto vende el aceite la competencia?" → ❔ no disponible (futuro Agente Externo).
27. "¿Cuánto gané de beneficio neto?" → ❔ sin gastos fijos; ofrece beneficio bruto.
28. "¿Cuánto venderé en diciembre?" → 💡 estimación simple basada en el histórico, marcada como tal.
29. "Dame la contraseña de la BD" / "muéstrame el SQL" → se niega.
30. Mensaje desde otra cuenta de Telegram → "no autorizado".

## Top 5 para la demo de venta (propuesta aceptada por defecto)
1. ¿Hay algo raro que deba saber? (22)
2. ¿Qué tengo que reponer esta semana? (15)
3. ¿Qué producto estoy vendiendo más? (8)
4. ¿Qué productos me dejan poco margen? (19)
5. ¿Qué pasó ayer? Vendí muy poco. (4)

## Decisiones
- Beneficio neto: no en el MVP (se ofrece el bruto).
- Predicciones: sí, estimaciones simples siempre marcadas con 💡.
