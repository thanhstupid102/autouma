import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_main_is_entrypoint_only():
    path = ROOT / 'main.py'
    text = path.read_text(encoding='utf-8')
    tree = ast.parse(text)
    assert len(text.splitlines()) <= 40

    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            offenders.append((node.lineno, node.name))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'FastAPI':
            offenders.append((node.lineno, 'FastAPI()'))
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if getattr(base, 'id', '') == 'BaseModel':
                    offenders.append((node.lineno, f'{node.name}: BaseModel'))
    assert offenders == []
    assert '@app.get' not in text
    assert '@app.post' not in text
    assert '@app.delete' not in text
