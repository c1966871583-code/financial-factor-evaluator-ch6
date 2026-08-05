from backend.amr.financial_p3_combinations import evaluate_financial_p3_combinations
from backend.amr.financial_p3_info_gain_m_comparisons import MInfoGainComparisonConfig
from backend.amr.financial_p3_info_gain_m_member_baselines import evaluate_financial_p3_info_gain_m_member_baselines
from tests.fixtures.synthetic_financial_p3_combination_cases import make_batch,make_configuration as combo_config
from tests.fixtures.synthetic_financial_p3_info_gain_m_member_baseline_cases import make_prepared_inputs,make_configuration as member_config
def make_inputs(): return evaluate_financial_p3_combinations(make_batch(),configuration=combo_config()),evaluate_financial_p3_info_gain_m_member_baselines(make_prepared_inputs(),configuration=member_config())
def make_configuration(**changes):
 v={"run_id":"SYNTHETIC-FIN-P3-INFO-GAIN-03A-01"};v.update(changes);return MInfoGainComparisonConfig(**v)
