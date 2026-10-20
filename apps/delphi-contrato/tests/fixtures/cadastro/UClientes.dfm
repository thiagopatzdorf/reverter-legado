object FrmClientes: TFrmClientes
  Left = 0
  Top = 0
  Caption = 'Cadastro de Clientes'
  ClientHeight = 320
  ClientWidth = 480
  OnShow = FormShow
  PixelsPerInch = 96
  TextHeight = 13
  object EdtNome: TEdit
    Left = 16
    Top = 16
    Width = 300
    Height = 21
    MaxLength = 60
    TabOrder = 0
  end
  object EdtCpf: TEdit
    Left = 16
    Top = 48
    Width = 120
    Height = 21
    MaxLength = 11
    TabOrder = 1
  end
  object BtnSalvar: TButton
    Left = 16
    Top = 80
    Caption = '&Salvar'
    TabOrder = 2
    OnClick = BtnSalvarClick
  end
  object BtnExcluir: TButton
    Left = 104
    Top = 80
    Caption = 'E&xcluir'
    TabOrder = 3
    OnClick = BtnExcluirClick
  end
  object GridClientes: TDBGrid
    Left = 16
    Top = 120
    Width = 448
    Height = 180
    DataSource = DsClientes
    Columns = <
      item
        FieldName = 'NOME'
        Title.Caption = 'Nome'
        Width = 300
      end
      item
        FieldName = 'CPF'
        Width = 120
      end>
  end
  object DsClientes: TDataSource
    DataSet = DmDados.QryClientes
  end
end
