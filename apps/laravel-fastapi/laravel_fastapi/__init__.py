"""Laravel -> contrato -> FastAPI, com avaliador diferencial."""
import sys
from pathlib import Path

# O runtime vai copiado para dentro do app gerado; aqui ele é importado do pacote.
_RUNTIME = str(Path(__file__).resolve().parent / "runtime")
if _RUNTIME not in sys.path:
    sys.path.insert(0, _RUNTIME)
