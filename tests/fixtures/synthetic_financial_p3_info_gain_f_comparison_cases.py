from backend.amr.financial_p3_combinations import evaluate_financial_p3_combinations
from backend.amr.financial_p3_info_gain_f_comparisons import FInfoGainComparisonConfig
from backend.amr.financial_p3_info_gain_f_member_baselines import evaluate_financial_p3_info_gain_f_member_baselines
from tests.fixtures.synthetic_financial_p3_combination_cases import make_batch,make_configuration as cc
from tests.fixtures.synthetic_financial_p3_info_gain_f_member_baseline_cases import make_prepared_inputs,make_configuration as fc
def make_inputs():return evaluate_financial_p3_combinations(make_batch(),configuration=cc()),evaluate_financial_p3_info_gain_f_member_baselines(make_prepared_inputs(),configuration=fc())
def make_configuration(**changes):
 v={"run_id":"SYNTHETIC-FIN-P3-INFO-GAIN-03B-01"};v.update(changes);return FInfoGainComparisonConfig(**v)
