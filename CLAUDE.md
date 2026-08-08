# Rama de trabajo

`main` es la rama de despliegue real en Render (la que usan ambos servicios,
`oposicion-age` y `oposicion-age-frontend`) y la rama de trabajo principal.
`claude/exam-prep-web-platform-07flxz` fue la rama de despliegue anterior;
ya no la usa Render.

Todo el desarrollo, commits y push deben ir a `main` salvo que el usuario
pida explícitamente lo contrario.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
