"""Export the public allowlist only, excluding local references, datasets and all repository history."""
import argparse,hashlib,json,subprocess,zipfile
from pathlib import Path
from check_release import ROOT,check
VERSION=(ROOT/'src/app/_version.py').read_text().split('"')[1]

PRIVATE='references/private'

def _private_files():
    """references/private/** for a coordinator bundle; refused unless Git would ignore every file."""
    base=ROOT/PRIVATE
    if not base.is_dir():return []
    lines={l.strip() for l in (ROOT/'.gitignore').read_text().splitlines()}
    if '/references/private/' not in lines:raise ValueError('.gitignore must ignore /references/private/')
    files=sorted(p for p in base.rglob('*') if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts)
    proc=subprocess.run(['git','rev-parse','--show-toplevel'],cwd=ROOT,capture_output=True,text=True)
    if proc.returncode==0:
        for p in files:
            rel=p.relative_to(ROOT).as_posix()
            if subprocess.run(['git','check-ignore','-q',rel],cwd=ROOT).returncode!=0:raise ValueError('not ignored by git: '+rel)
            if subprocess.run(['git','ls-files','--error-unmatch',rel],cwd=ROOT,capture_output=True).returncode==0:raise ValueError('tracked private file: '+rel)
    return files

def export(destination,with_private=False):
    destination=Path(destination).resolve()
    if destination==ROOT or ROOT in destination.parents:raise ValueError('output must be outside the source tree')
    files,errors=check()
    if errors:raise ValueError('Release check failed: '+str(errors))
    files=[p for p in files if p.name!='PUBLIC_RELEASE_MANIFEST.json']
    private=_private_files() if with_private else []
    destination.parent.mkdir(parents=True,exist_ok=True)
    manifest={'version':VERSION,'privacy_scope':'Explicit allowlist, no enterprise reference payloads or Git history; not proof of public rights or absence of all confidential content.',
              'files':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    if with_private:
        manifest['private_scope']='Coordinator bundle: references/private/ is git-ignored local reference data. Do not publish this archive.'
        manifest['private_files']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in private}
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as z:
        for p in files+private:z.write(p,f'datamesh-toolkit-{VERSION}/'+p.relative_to(ROOT).as_posix())
        z.writestr(f'datamesh-toolkit-{VERSION}/PUBLIC_RELEASE_MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
    return len(files),len(private)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',required=True)
    ap.add_argument('--with-private',action='store_true',help='coordinator bundle: also include git-ignored references/private/')
    a=ap.parse_args();n,k=export(a.out,a.with_private)
    print(f'Exported {n} allowlisted files'+(f' + {k} private references (bundle: do not publish)' if a.with_private else '')+'. Review before publication.')
