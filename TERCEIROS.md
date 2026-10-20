# Programas de terceiros usados como caso de estudo

Os casos foram feitos sobre programas de código aberto, cada um usado só como alvo de
estudo. Nenhum deles tem relação com este projeto, e nenhum foi alterado. Os arquivos
abaixo derivam desses programas (telas lidas do executável, pseudo-código decompilado,
textos e listas extraídos) e seguem a licença do programa de origem, não a MIT.

| caso | programa | licença | arquivos derivados | origem |
|---|---|---|---|---|
| Delphi → contrato | HeidiSQL 12.21, de Ansgar Becker e colaboradores | GPL-2.0 | `apps/delphi-contrato/casos/heidisql-dados/`, `apps/delphi-contrato/casos/heidisql-rea/` | https://www.heidisql.com/ · https://github.com/HeidiSQL/HeidiSQL |
| REA num jogo | Chocolate Doom 3.1.1 | GPL-2.0 | `apps/rea-lab/casos/chocolate-doom/evidencia/` (exceto `freedoom1.wad.json`) | https://github.com/chocolate-doom/chocolate-doom |
| REA num jogo | Freedoom 0.13.0 | BSD-3-Clause | `apps/rea-lab/casos/chocolate-doom/evidencia/freedoom1.wad.json` | https://github.com/freedoom/freedoom |
| Laravel → FastAPI | laravel-realworld-example-app (f1amy) | MIT | `apps/laravel-fastapi/casos/realworld/evidencia/` | https://github.com/f1amy/laravel-realworld-example-app |
| Laravel → FastAPI | BookStack v26.09.1 | MIT | `apps/laravel-fastapi/casos/bookstack/bookstack.json` | https://github.com/BookStackApp/BookStack |

Ferramentas de terceiros usadas, não incluídas aqui: REA (`rea-agents` 6.7.0, MIT,
https://github.com/morluto/rea), Ghidra 12.1.4 (Apache-2.0), tree-sitter e
tree-sitter-php (MIT). As versões estão fixadas no código.
