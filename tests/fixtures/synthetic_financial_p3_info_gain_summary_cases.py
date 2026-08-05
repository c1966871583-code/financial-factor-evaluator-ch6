from backend.amr.financial_p3_info_gain_m_comparisons import compare_financial_p3_info_gain_m
from backend.amr.financial_p3_info_gain_f_comparisons import compare_financial_p3_info_gain_f
from backend.amr.financial_p3_info_gain_r_comparisons import compare_financial_p3_info_gain_r
from backend.amr.financial_p3_info_gain_coverage import report_financial_p3_info_gain_coverage
from backend.amr.financial_p3_info_gain_summary import InfoGainSummaryConfig
from tests.fixtures.synthetic_financial_p3_info_gain_m_comparison_cases import make_inputs as mi,make_configuration as mc
from tests.fixtures.synthetic_financial_p3_info_gain_f_comparison_cases import make_inputs as fi,make_configuration as fc
from tests.fixtures.synthetic_financial_p3_info_gain_r_comparison_cases import make_inputs as ri,make_configuration as rc
from tests.fixtures.synthetic_financial_p3_info_gain_coverage_cases import make_inputs as ci,make_configuration as cc
def make_inputs():
 m=compare_financial_p3_info_gain_m(*mi(),configuration=mc());f=compare_financial_p3_info_gain_f(*fi(),configuration=fc());r=compare_financial_p3_info_gain_r(*ri(),configuration=rc());c=report_financial_p3_info_gain_coverage(*ci(),configuration=cc());return m,f,r,c
def make_configuration(**changes):
 v={"run_id":"SYNTHETIC-FIN-P3-INFO-GAIN-05-01"};v.update(changes);return InfoGainSummaryConfig(**v)
