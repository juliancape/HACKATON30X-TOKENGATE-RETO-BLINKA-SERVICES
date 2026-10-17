# Agente de Compras Corporativas con IA

## Descripción

Aplicación que permite a los empleados solicitar comida mediante lenguaje natural a través de WhatsApp. Utiliza un LLM para gestionar la conversación, Rappi para buscar productos y preparar pedidos, y Jev (TypeSafe AI) para evaluar las opciones según el histórico de precios y las políticas de gasto corporativas.

El objetivo es automatizar la preparación de compras, evaluar su cumplimiento con las políticas de la empresa y enviar las decisiones al core de facturación, sin ejecutar pagos durante el MVP.

## Flujo del sistema

1. **Solicitud por WhatsApp:** el empleado escribe lo que desea comprar.
2. **Recopilación de requisitos:** el LLM interpreta la solicitud y envía un formulario interactivo de WhatsApp mediante Kapso para completar los datos necesarios.
3. **Búsqueda en Rappi:** el backend consulta restaurantes, productos, precios y disponibilidad para generar opciones candidatas.
4. **Consulta del histórico y evaluación con Jev:** el backend consulta Supabase para obtener el histórico de precios y las políticas corporativas. Jev evalúa las opciones utilizando este contexto estructurado y genera una decisión: aprobar, rechazar o escalar.
5. **Presentación de opciones:** el LLM comunica por WhatsApp las tres opciones que mejor se ajustan a la solicitud y sus precios, mediante botones interactivos.
6. **Selección del empleado:** si rechaza las opciones, el sistema envía otro formulario para recopilar nuevas preferencias y repetir la búsqueda. Si acepta una opción, se valida nuevamente su precio y las condiciones de compra.
7. **Checkout y core de facturación:** el sistema prepara el pedido hasta el checkout de Rappi, sin realizar el pago, y envía al core de facturación el registro de la solicitud junto con su decisión y estado.

## Componentes y tecnologías

- **Kapso + WhatsApp Sandbox:** canal de comunicación, formularios y botones interactivos.
- **LLM:** interpretación del lenguaje natural, recopilación de requisitos y presentación de resultados.
- **Jev (TypeSafe AI):** evaluación estructurada de opciones según el histórico de precios, las políticas de gasto y el contexto de la solicitud.
- **Rappi CLI:** búsqueda de productos, consulta de precios, gestión del carrito y preparación del checkout.
- **Python 3.13.x + FastAPI:** backend, orquestación del flujo, validación de reglas y control de estados.
- **uv:** gestión del entorno virtual, dependencias y ejecución del proyecto Python.
- **Supabase:** PostgreSQL administrado para almacenar el histórico de precios, políticas corporativas, solicitudes, decisiones y auditoría.
- **Core de facturación:** recepción del registro de compra y de su decisión para la gestión correspondiente.

## Estándares de desarrollo en Python

El código debe seguir buenas prácticas de ingeniería de software, priorizando la mantenibilidad, la reutilización, la legibilidad y la seguridad.

- **Arquitectura modular:** separar responsabilidades en módulos y paquetes, evitando archivos excesivamente grandes y dependencias innecesarias entre componentes.
- **Código reutilizable:** evitar duplicación mediante funciones, servicios y componentes compartidos.
- **Clases y modelos:** utilizar clases cuando aporten encapsulación o agrupación de responsabilidades; emplear modelos tipados, por ejemplo con Pydantic, para validar solicitudes, respuestas y estructuras de datos.
- **Decoradores:** utilizarlos cuando aporten valor, por ejemplo para dependencias transversales, medición de tiempo o instrumentación, evitando complejidad innecesaria.
- **Variables de entorno:** gestionar credenciales, tokens, claves API y configuración mediante variables de entorno y un archivo `.env` local excluido del control de versiones. Validar la configuración al iniciar la aplicación y no incluir secretos en el código.
- **Tipado y calidad:** utilizar type hints, convenciones PEP 8, nombres descriptivos y funciones con responsabilidades claras. Incorporar linting y formateo automático.
- **Logging:** implementar logs estructurados con niveles apropiados (`DEBUG`, `INFO`, `WARNING`, `ERROR`), contexto de las operaciones y manejo de excepciones. Nunca registrar tokens, credenciales ni datos sensibles innecesarios.
- **Manejo de errores:** gestionar fallos de servicios externos, respuestas inválidas, timeouts y errores de integración sin perder la trazabilidad de las solicitudes.
- **Pruebas:** incorporar pruebas unitarias para las reglas de negocio y pruebas de integración para Supabase, Jev, Rappi y Kapso cuando corresponda.
- **Seguridad:** validar entradas, proteger endpoints, verificar autorizaciones en el backend y mantener los secretos fuera del frontend.
- **Gestión de dependencias:** utilizar `uv` y `pyproject.toml`, fijando y manteniendo un archivo `uv.lock` reproducible.

## Papel de Jev

Jev interviene después de obtener opciones reales de Rappi y consultar los datos relevantes en Supabase. Evalúa las opciones mediante decisiones estructuradas, mientras el backend aplica las restricciones obligatorias y controla las acciones permitidas.

La aceptación del empleado representa una preferencia de compra y no sustituye la aprobación corporativa. Las solicitudes escaladas quedan pendientes de un mecanismo de revisión que se definirá posteriormente.

## Alcance del MVP

- Solicitudes de compra mediante WhatsApp.
- Recopilación interactiva de requisitos.
- Búsqueda real de productos en Rappi.
- Consulta del histórico de precios y políticas en Supabase.
- Evaluación de decisiones mediante Jev.
- Presentación y selección de opciones mediante botones.
- Preparación del pedido hasta el checkout, sin pago.
- Envío del registro y estado de la solicitud al core de facturación.
- Trazabilidad de solicitudes y decisiones.

## Configuración de desarrollo

- Python **3.13.x**.
- `uv` para la gestión de dependencias y del entorno.
- FastAPI para el backend.
- Supabase para persistencia.
- Variables de entorno para credenciales y configuración de servicios externos.

El mecanismo de revisión de solicitudes escaladas y el tratamiento definitivo de los registros en el core de facturación quedan pendientes de definición.
