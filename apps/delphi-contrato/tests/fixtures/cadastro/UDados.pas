unit UDados;

interface

uses
  SysUtils, Classes, DB, ADODB;

type
  TDmDados = class(TDataModule)
    Conexao: TADOConnection;
    QryClientes: TADOQuery;
  private
    { Private declarations }
  public
    function ProximoCodigo(const Tabela: string): Integer;
  end;

  TStatusPedido = (spAberto, spFaturado, spCancelado);

  TTotais = record
    Bruto: Currency;
    Desconto, Liquido: Currency;
  end;

function CalcularDesconto(Valor: Currency; Percentual: Double = 0): Currency;
procedure RegistrarLog(const Msg: string); overload;

var
  DmDados: TDmDados;

implementation

{$R *.dfm}

(* Regra herdada do sistema antigo: desconto acima de 15% exige gerente *)
function CalcularDesconto(Valor: Currency; Percentual: Double): Currency;
begin
  if Percentual > 15 then
    raise Exception.Create('Desconto acima de 15% exige gerente');
  Result := Valor * Percentual / 100;
end;

procedure RegistrarLog(const Msg: string);
begin
  // grava no arquivo de log do dia
end;

function TDmDados.ProximoCodigo(const Tabela: string): Integer;
var
  Q: TADOQuery;
begin
  Q := TADOQuery.Create(nil);
  try
    Q.Connection := Conexao;
    Q.SQL.Add('SELECT MAX(CODIGO) AS ULTIMO');
    Q.SQL.Add('FROM ' + Tabela);
    Q.Open;
    Result := Q.FieldByName('ULTIMO').AsInteger + 1;
  finally
    Q.Free;
  end;
end;

end.
