"""Comprobación local del lector de totales mensuales (sin descargar fuentes)."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import sys

sys.modules.setdefault("bs4", SimpleNamespace(BeautifulSoup=None))
sys.modules.setdefault("pypdf", SimpleNamespace(PdfReader=lambda stream: SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda: SAMPLE)])))
spec=spec_from_file_location("pipeline",Path(__file__).with_name("update_pipeline.py"))
pipeline=module_from_spec(spec)
spec.loader.exec_module(pipeline)
pipeline.fetch=lambda *args,**kwargs: b"%PDF-mock"

SAMPLE="""Power BI Desktop Exportaciones 0 10 20 Promedio en MMm3
julio agosto septiembre octubre noviembre diciembre enero febrero marzo abril mayo junio julio
2025 2026
6,52 6,92 4,04 7,12 8,05 6,40 8,63 10,06 10,34 9,71 7,52 7,00 6,67
6,1 6,6 3,8 6,5 7,4 5,6 8,1 9,2 9,3 9,0 7,2 6,6 6,3
Pais Brasil Chile Uruguay Importaciones 0 5 10 15 Promedio en MMm3
julio agosto septiembre octubre noviembre diciembre enero febrero marzo abril mayo junio julio
2025 2026
15,90 9,53 1,13 0,00 0,00 0,14 0,81 0,84 0,57 1,03 4,94 16,77 8,94
1,83 1,91 14,64 7,70 3,04 15,84 7,79 Pais Bolivia Chile GNL"""
assert pipeline._read_monthly_flows_pdf("2026-07")=={"exports":6.67,"imports":8.94}
data={"systemMonthly2026":[{"month":"2026-07","imports":"8,94","exports":"6,67"}],
      "systemMonthlyMeta":{"latest":"2026-07"},"systemKpis":[],"updates":[{"name":"Flujos mensuales"}]}
pipeline.fetch=lambda *args,**kwargs: b"Agosto 2026 Enero 2026"
pipeline._read_monthly_flows_pdf=lambda month: {"imports":8.94,"exports":6.67} if month=="2026-07" else {"imports":9.10,"exports":6.80}
pipeline.monthly_flows_status(data)
assert data["systemMonthlyMeta"]["latest"]=="2026-08"
assert data["systemMonthly2026"][-1]["imports"]=="9,10"
assert "lng" not in data["systemMonthly2026"][-1]
assert data["updates"][0]["status"]=="new_report"
print("Lector mensual: totales julio 2026 coinciden con el informe validado")
