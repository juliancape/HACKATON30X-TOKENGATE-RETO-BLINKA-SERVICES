## Componentes y tecnologías

- **Kapso + WhatsApp Sandbox:** canal de comunicación, formularios y botones interactivos.
- **LLM:** interpretación del lenguaje natural, recopilación de requisitos y presentación de resultados.
- **Jev (TypeSafe AI):** evaluación estructurada de opciones según el histórico de precios, las políticas de gasto y el contexto de la solicitud.
- **Rappi CLI:** integración para buscar productos, consultar restaurantes, gestionar el carrito y preparar el checkout.
  - Repositorio: https://github.com/crafter-station/rappi-cli
  - Runtime y gestor de paquetes: Bun.
  - Integración mediante CLI o API REST local, según las necesidades del backend.
- **Python 3.13.x + FastAPI:** backend, orquestación del flujo, validación de reglas y control de estados.
- **uv:** gestión del entorno virtual, dependencias y ejecución del proyecto Python.
- **Supabase:** PostgreSQL administrado para almacenar el histórico de precios, políticas corporativas, solicitudes, decisiones y auditoría.
- **Core de facturación:** recepción del registro de compra y de su decisión para la gestión correspondiente.

## Integración de Rappi CLI

El proyecto utilizará [crafter-station/rappi-cli](https://github.com/crafter-station/rappi-cli) como integración con Rappi.

Bun debe instalarse en el entorno de desarrollo y estar disponible en el `PATH`. El CLI se instalará globalmente o desde el repositorio, según la configuración elegida.

Instalación de Bun: https://bun.com/docs/installation

Instalación de Rappi CLI:

```bash
# Instalar Bun si aún no está disponible.
curl -fsSL https://bun.com/install | bash

# Verificar la instalación.
bun --version

# Instalar Rappi CLI globalmente.
bun add -g @crafter/rappi-cli

# Autenticar la cuenta de Rappi.
rappi login
```

La autenticación debe realizarse de forma segura y las credenciales deben mantenerse fuera del repositorio.

Antes de integrar la herramienta con el backend, se verificará el funcionamiento de la búsqueda, consulta de productos, gestión del carrito y vista previa del checkout. El MVP no ejecutará `rappi place-order` ni realizará pagos.

## Estándares de desarrollo en Python

El código debe seguir buenas prácticas de ingeniería de software, priorizando la mantenibilidad, reutilización, legibilidad y seguridad.

- **Arquitectura modular:** separar responsabilidades en módulos y paquetes, evitando archivos excesivamente grandes.
- **Código reutilizable:** evitar duplicación mediante funciones, servicios y componentes compartidos.
- **Clases y modelos:** utilizar clases cuando aporten encapsulación y modelos tipados con Pydantic para validar entradas, respuestas y estructuras de datos.
- **Decoradores:** emplearlos cuando aporten valor para instrumentación, medición de tiempo o comportamientos transversales.
- **Variables de entorno:** gestionar credenciales, tokens y configuración mediante variables de entorno; utilizar `.env` local excluido del control de versiones y validar la configuración al iniciar.
- **Tipado y calidad:** utilizar type hints, convenciones PEP 8, nombres descriptivos y funciones con responsabilidades claras.
- **Logging:** implementar logs estructurados con niveles apropiados y contexto de las operaciones, sin registrar credenciales ni información sensible innecesaria.
- **Manejo de errores:** controlar fallos de servicios externos, timeouts, respuestas inválidas y errores de integración.
- **Pruebas:** incorporar pruebas unitarias para las reglas de negocio y pruebas de integración para Supabase, Jev, Rappi y Kapso.
- **Seguridad:** validar entradas, verificar autorizaciones en el backend y mantener los secretos fuera del frontend.
- **Gestión de dependencias:** utilizar `uv`, `pyproject.toml` y `uv.lock` para mantener un entorno reproducible.

## Configuración de desarrollo

- Python **3.13.x** para el backend.
- `uv` para las dependencias y el entorno Python.
- **Bun** para instalar y ejecutar Rappi CLI.
- FastAPI para el backend.
- Supabase para persistencia.
- Variables de entorno para configurar servicios externos.

Las versiones de Python y Bun deben verificarse en el entorno de desarrollo y mantenerse documentadas para asegurar la reproducibilidad.
