unit UClientes;

interface

uses
  Windows, SysUtils, Classes, Controls, Forms, StdCtrls, DB, ADODB, Grids, DBGrids,
  UDados;

type
  TFrmClientes = class(TForm)
    EdtNome: TEdit;
    EdtCpf: TEdit;
    BtnSalvar: TButton;
    BtnExcluir: TButton;
    GridClientes: TDBGrid;
    DsClientes: TDataSource;
    procedure FormShow(Sender: TObject);
    procedure BtnSalvarClick(Sender: TObject);
    procedure BtnExcluirClick(Sender: TObject);
  private
    FCodigoAtual: Integer;
    function CpfValido(const Cpf: string): Boolean;
  public
    property CodigoAtual: Integer read FCodigoAtual write FCodigoAtual;
  end;

var
  FrmClientes: TFrmClientes;

implementation

{$R *.dfm}

procedure TFrmClientes.FormShow(Sender: TObject);
begin
  DmDados.QryClientes.Open;
end;

function TFrmClientes.CpfValido(const Cpf: string): Boolean;
begin
  Result := Length(Cpf) = 11; { simplificado no legado }
end;

procedure TFrmClientes.BtnSalvarClick(Sender: TObject);
var
  Q: TADOQuery;
begin
  if not CpfValido(EdtCpf.Text) then
    raise Exception.Create('CPF inválido');
  Q := TADOQuery.Create(nil);
  try
    Q.Connection := DmDados.Conexao;
    Q.SQL.Text := 'INSERT INTO CLIENTES (CODIGO, NOME, CPF) ' +
      'VALUES (:CODIGO, :NOME, :CPF)';
    Q.Parameters.ParamByName('CODIGO').Value := DmDados.ProximoCodigo('CLIENTES');
    Q.Parameters.ParamByName('NOME').Value := EdtNome.Text;
    Q.Parameters.ParamByName('CPF').Value := EdtCpf.Text;
    Q.ExecSQL;
  finally
    Q.Free;
  end;
end;

end.
