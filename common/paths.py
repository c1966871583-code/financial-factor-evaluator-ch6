from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / 'data'
TEST_DOCS_DIR = REPO_ROOT / 'test_docs'
RUNTIME_DIR = REPO_ROOT / 'runtime'

for path in (DATA_DIR, TEST_DOCS_DIR, RUNTIME_DIR):
    path.mkdir(parents=True, exist_ok=True)

def data_path(*parts):
    return DATA_DIR.joinpath(*parts)

def runtime_path(*parts):
    return RUNTIME_DIR.joinpath(*parts)
