from backend.amr.financial_p3_research_log_contract import ResearchLogSchema
from backend.amr.financial_p3_research_log_serialization import assemble_financial_p3_research_log
from tests.fixtures.synthetic_financial_p3_research_log_config_cases import make_snapshot as config
from tests.fixtures.synthetic_financial_p3_research_log_result_cases import make_snapshot as results
from tests.fixtures.synthetic_financial_p3_research_log_failure_cases import make_snapshot as failures
from tests.fixtures.synthetic_financial_p3_research_log_lineage_cases import make_snapshot as lineage
def make_inputs():return ResearchLogSchema(),config(),results(),failures(),lineage()
def make_log():return assemble_financial_p3_research_log(*make_inputs())
