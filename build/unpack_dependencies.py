"""Expand the bundled build inputs under this project's cache, with SHA verification."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,os,tarfile

ROOT=Path(__file__).resolve().parents[1]
def unpack(selected=None,verify=False):
    inventory=json.loads((ROOT/'build/dependencies/manifest.json').read_text('utf-8'))
    cache=ROOT/'.cache/build_dependencies';cache.mkdir(parents=True,exist_ok=True)
    results={}
    for row in inventory['archives']:
        name=Path(row['path']).name.removesuffix('.tar.gz')
        if selected and name not in selected:continue
        archive=ROOT/row['path'];digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest!=row['sha256']:raise ValueError('Build archive differs: '+row['path'])
        local=cache/name
        # TensorFlow includes example paths beyond legacy Windows MAX_PATH.
        dest=Path('\\\\?\\'+str(local.resolve()))if os.name=='nt'else local
        receipt=dest/'.archive_sha256'
        current=receipt.is_file()and receipt.read_text('ascii').strip()==digest
        if not current:
            if receipt.exists():raise FileExistsError('Dependency archive changed; preserve the existing cache: '+str(local))
            dest.mkdir(exist_ok=True)
            expected=iter(row['members'])
            with tarfile.open(archive,'r:gz')as tar:
                for member in tar:
                    relative=PurePosixPath(member.name)
                    if relative.is_absolute()or'..'in relative.parts:raise ValueError('Unsafe dependency member')
                    target=dest.joinpath(*relative.parts)
                    if member.isdir():target.mkdir(parents=True,exist_ok=True);continue
                    source=tar.extractfile(member)
                    if source is None:raise ValueError('Unsupported dependency member: '+member.name)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    item=next(expected);digest_written=hashlib.sha256();bytes_written=0
                    if item['path']!=member.name:raise ValueError('Dependency member order differs')
                    with source,target.open('wb')as output:
                        while block:=source.read(1<<20):
                            output.write(block);digest_written.update(block);bytes_written+=len(block)
                    if bytes_written!=item['bytes']or digest_written.hexdigest()!=item['sha256']:raise ValueError('Dependency content differs: '+member.name)
                    if os.name!='nt':target.chmod(member.mode&0o777)
            if next(expected,None)is not None:raise ValueError('Dependency archive is incomplete')
        if verify and current:
            final={item['path']:item for item in row['members']}
            for name_in_archive,item in final.items():
                p=dest/name_in_archive
                if not p.is_file()or p.stat().st_size!=item['bytes']or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:
                    raise ValueError('Extracted dependency differs: '+name_in_archive)
        receipt.write_text(digest+'\n','ascii');results[name]=local
    return results

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--verify',action='store_true');args=parser.parse_args()
    print(json.dumps(dict(status='PASS',directories={k:str(v)for k,v in unpack(verify=args.verify).items()})))
