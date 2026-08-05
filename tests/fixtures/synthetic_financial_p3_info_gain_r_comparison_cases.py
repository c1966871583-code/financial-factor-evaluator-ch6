from backend.amr.financial_p3_combinations import evaluate_financial_p3_combinations
from backend.amr.financial_p3_info_gain_r_comparisons import RInfoGainComparisonConfig
from backend.amr.financial_p3_info_gain_r_member_baselines import evaluate_financial_p3_info_gain_r_member_baselines
from tests.fixtures.synthetic_financial_p3_combination_cases import make_batch,make_configuration as cc
from tests.fixtures.synthetic_financial_p3_info_gain_r_member_baseline_cases import make_prepared_inputs,make_configuration as rc
def make_inputs():return evaluate_financial_p3_combinations(make_batch(),configuration=cc()),evaluate_financial_p3_info_gain_r_member_baselines(make_prepared_inputs(),configuration=rc())
def make_configuration(**changes):
 v={"run_id":"SYNTHETIC-FIN-P3-INFO-GAIN-03C-01"};v.update(changes);return RInfoGainComparisonConfig(**v)
