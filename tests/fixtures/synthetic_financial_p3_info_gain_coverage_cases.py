from backend.amr.financial_p3_combinations import evaluate_financial_p3_combinations
from backend.amr.financial_p3_info_gain_coverage import CoverageConfig
from backend.amr.financial_p3_info_gain_inputs import prepare_financial_p3_info_gain_inputs
from tests.fixtures.synthetic_financial_p3_combination_cases import make_batch,make_configuration as cc
from tests.fixtures.synthetic_financial_p3_info_gain_input_cases import make_batches,make_configuration as ic
def make_inputs():return evaluate_financial_p3_combinations(make_batch(),configuration=cc()),prepare_financial_p3_info_gain_inputs(make_batches(),configuration=ic())
def make_configuration(**changes):
 v={"run_id":"SYNTHETIC-FIN-P3-INFO-GAIN-04-01"};v.update(changes);return CoverageConfig(**v)
