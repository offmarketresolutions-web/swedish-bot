"""One-shot codegen: swap the 5 rendered agent-prompt constants in kb/seed_prompts.py
with the reviewed+validated refined bodies in tools/refined/. Keeps the doc-only INTAKE,
LANGUAGE_DIRECTIVE and all_prompts() untouched. Verified immediately by the test suite."""
import re
import pathlib

REFINED = pathlib.Path("tools/refined")
SEED = pathlib.Path("kb/seed_prompts.py")
CONSTS = {"ROUTER": "router", "SPECIALIST": "specialist",
          "INTELLIGENT_INTAKE": "intelligent_intake", "SUMMARIZER": "summarizer", "SAFETY": "safety"}


def body_of(name):
    txt = (REFINED / f"{name}.txt").read_text(encoding="utf-8").strip()
    # strip an optional `NAME = """ ... """` wrapper some agents included
    m = re.match(r'^\w+\s*=\s*"""(.*)"""\s*$', txt, re.DOTALL)
    if m:
        txt = m.group(1)
    assert '"""' not in txt, f"{name}: body contains triple-quote"
    return txt


text = SEED.read_text(encoding="utf-8")
for const, fname in CONSTS.items():
    body = body_of(fname)
    pat = re.compile(rf'{const} = """.*?"""', re.DOTALL)
    assert pat.search(text), f"{const} not found in seed_prompts.py"
    text = pat.sub(lambda _m, b=body: f'{const} = """{b}"""', text, count=1)
SEED.write_text(text, encoding="utf-8")
print("rebuilt seed_prompts.py with refined ROUTER/SPECIALIST/INTELLIGENT_INTAKE/SUMMARIZER/SAFETY")
