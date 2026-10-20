program Cadastro;

uses
  Forms,
  UDados in 'UDados.pas' {DmDados: TDataModule},
  UClientes in 'UClientes.pas' {FrmClientes};

{$R *.res}

begin
  Application.Initialize;
  Application.CreateForm(TDmDados, DmDados);
  Application.CreateForm(TFrmClientes, FrmClientes);
  Application.Run;
end.
