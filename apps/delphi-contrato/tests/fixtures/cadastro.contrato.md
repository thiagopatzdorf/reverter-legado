# Contrato do sistema Delphi

5 arquivos lidos: 3 units, 2 formulários, 8 componentes, 3 eventos (2 implementados), 3 comandos SQL sobre 2 tabelas, 3 pendências.

## Operações (clique → rotina → SQL)

| operação | rotina | tabelas | parâmetros | implementada |
|---|---|---|---|---|
| `FrmClientes.BtnExcluir.OnClick` | `TFrmClientes.BtnExcluirClick` | — | — | **não** |
| `FrmClientes.BtnSalvar.OnClick` | `TFrmClientes.BtnSalvarClick` | CLIENTES | CODIGO, CPF, NOME | sim |
| `FrmClientes.FrmClientes.OnShow` | `TFrmClientes.FormShow` | CIDADES, CLIENTES | ATIVO | sim |

## Regras com assinatura (interface das units)

- `UDados.CalcularDesconto(Valor: Currency, Percentual: Double = 0): Currency`
- `UDados.RegistrarLog(Msg: string)`

## Tabelas

| tabela | onde aparece |
|---|---|
| CIDADES | `UDados.dfm:QryClientes.SQL.Strings` |
| CLIENTES | `UClientes.pas:53`, `UDados.dfm:QryClientes.SQL.Strings` |

## Pendências

- **evento_sem_implementacao** em `UClientes.dfm:BtnExcluir.OnClick`: TFrmClientes.BtnExcluirClick (declarado na classe, sem corpo)
- **metodo_sem_corpo** em `UClientes.pas`: TFrmClientes.BtnExcluirClick
- **sql_dinamico** em `UDados.pas:55`: parte do SQL vem de variável; a tabela real só aparece em execução
