"""Limited public-release checks. Not a DLP guarantee or a rights review."""
from pathlib import Path
import re,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
TOP={'README.md','CHANGELOG.md','SECURITY.md','DATA_POLICY.md','LICENSE.txt','pyproject.toml','MANIFEST.in','requirements-ci.txt','.gitignore','PUBLIC_RELEASE_MANIFEST.json','.dockerignore'}
REF={'references/README.md','references/public/manifest.example.json'}

def allowed(rel):
    p=Path(rel)
    if any(x in {'__pycache__','.git','.venv','private','build','dist'} or x.endswith('.egg-info') for x in p.parts):return False
    if rel in TOP or rel in REF:return True
    if rel in {'deploy/local/compose.json','deploy/local/Dockerfile','deploy/local/runtime.py','deploy/local/init_postgres.sh'}:return True
    if rel.startswith('src/'):
        return rel.startswith(('src/app/application/gauge/','src/app/application/simulation/','src/app/application/process/','src/app/application/plate/','src/app/application/messaging/','src/app/application/enrichment/','src/app/application/probe/','src/app/application/ingest/','src/app/application/persistence/','src/app/application/splice/','src/app/application/common/','src/app/application/hfgt/','src/app/domain/','src/app/infrastructure/gauge/','src/app/infrastructure/tensors/','src/app/infrastructure/plate/','src/app/infrastructure/messaging/','src/app/infrastructure/enrichment/','src/app/infrastructure/probe/','src/app/infrastructure/ingest/','src/app/infrastructure/persistence/','src/app/infrastructure/splice/','src/app/infrastructure/hfgt/, "src/app/interfaces/__init__.py",
"src/app/interfaces/http/**/*.py",
"docs/architecture/HTTP_API.md",
"docs/contracts/OPENAPI.json",
"scripts/gen_openapi.py",
"tests/test_http_api.py",
"tests/test_http_settings.py",
"tests/test_http_layering.py",
"tests/test_jetstream_token.py",')) and p.suffix=='.py' or rel in {'src/app/__init__.py','src/app/_version.py','src/app/application/__init__.py','src/app/infrastructure/__init__.py'}
    return (rel.startswith(('tests/','scripts/')) and p.suffix in {'.py','.sh'} or
            rel.startswith('tests/fixtures/') and p.suffix=='.json' or
            rel.startswith('docs/') and p.suffix in {'.md','.json'} or
            rel=='.github/workflows/public-ci.yml')

PATTERNS={
 'internal URL':re.compile(r'https?://[^\s<>\)"\x27]*(?:clickup\.com|sharepoint\.com)|https://(?:task|doc|attachment|comment|chat|space|list|folder)-\d+',re.I),
 'email address':re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b',re.I),
 'private key':re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
 'known credential prefix':re.compile(r'\b(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16})\b'),
 'credential assignment':re.compile(r'(?:password|api_key|access_token|client_secret)\s*[=:]\s*["\x27][^"\x27]{8,}["\x27]',re.I),
}

def candidates(root=ROOT):
    return sorted(p for p in root.rglob('*') if p.is_file() and allowed(p.relative_to(root).as_posix()))

def check(root=ROOT,git_check=True):
    errors=[];files=candidates(root)
    # Follow no symlinks, even if they masquerade as a whitelisted path.
    for p in root.rglob('*'):
        if p.is_symlink() and '.git' not in p.relative_to(root).parts:errors.append('symlink forbidden: '+p.relative_to(root).as_posix())
    for p in files:
        rel=p.relative_to(root).as_posix()
        try:t=p.read_text()
        except (UnicodeError,OSError):errors.append('unreviewed nontext file: '+rel);continue
        for name,pattern in PATTERNS.items():
            hits=pattern.findall(t)
            if name=='email address':hits=[h for h in hits if not h.lower().endswith('@example.invalid') and h != 'postgresql@18-datamesh.service']  # RFC 6761 reserved, synthetic only
            if hits:errors.append(name+': '+rel)
    if git_check:
        proc=subprocess.run(['git','rev-parse','--show-toplevel'],cwd=root,capture_output=True,text=True)
        if proc.returncode==0:
            git_root=Path(proc.stdout.strip()).resolve()
            if git_root!=root.resolve():errors.append('release must be checked as repository root, not a subdirectory')
            else:
                result=subprocess.run(['git','ls-files','-z'],cwd=root,capture_output=True,check=True)
                for n in result.stdout.decode().split('\0'):
                    if n and not allowed(n):errors.append('forbidden tracked path: '+n)
    return files,errors

if __name__=='__main__':
    files,errors=check()
    for e in errors:print('FAIL '+e)
    print(f'{len(files)} allowlisted text files checked; {len(errors)} issues. Limited checks only; manual review required.')
    raise SystemExit(bool(errors))
