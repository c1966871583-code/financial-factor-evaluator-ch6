from backend.amr.financial_p3_research_log_failures import collect_financial_p3_research_log_failures
from tests.fixtures.synthetic_financial_p3_info_gain_task_gate_cases import make_inputs
def make_inputs_for_log():
 summary,bad=make_inputs();return bad,summary
def make_snapshot():return collect_financial_p3_research_log_failures(*make_inputs_for_log())
