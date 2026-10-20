object DmDados: TDmDados
  OldCreateOrder = False
  Height = 150
  Width = 215
  object Conexao: TADOConnection
    LoginPrompt = False
    Provider = 'SQLOLEDB.1'
  end
  object QryClientes: TADOQuery
    Connection = Conexao
    SQL.Strings = (
      'SELECT C.CODIGO, C.NOME, C.CPF'
      'FROM CLIENTES C'
      'LEFT JOIN CIDADES CI ON CI.ID = C.CIDADE_ID'
      'WHERE C.ATIVO = :ATIVO'
      'ORDER BY C.NOME')
    Parameters = <
      item
        Name = 'ATIVO'
        DataType = ftBoolean
        Value = True
      end>
  end
end
