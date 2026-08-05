from backend.amr.financial_p3_info_gain_task_gate import InfoGainTaskGateConfig
from tests.fixtures.synthetic_financial_p3_info_gain_end_to_end_cases import run_pipeline
def make_inputs():return run_pipeline()
def make_configuration(**changes):
 v={"run_id":"SYNTHETIC-FIN-P3-INFO-GAIN-07-01"};v.update(changes);return InfoGainTaskGateConfig(**v)
