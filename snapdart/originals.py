"""Download originals for current sector members and analysis periods, resumably."""
import io
import json
import zipfile
import hashlib
from pathlib import Path
from .settings import DATA_ROOT
from .dart_client import DartClient,save_json
from dart_remote.repository import Repository

def download(sector=None):
    repo=Repository(sector);years=repo.years();client=DartClient()
    folder=DATA_ROOT/'xml_origin';folder.mkdir(parents=True,exist_ok=True)
    manifest={'sector':repo.sector.id,'years':years,'documents':[],'errors':[]}
    for company in repo.companies():
        for document in repo.documents(company['stock_code']):
            if document['year'] not in years:continue
            receipt=document['rcept_no'];destination=folder/receipt;target=destination/(receipt+'.xml')
            try:
                if not target.exists():
                    raw=client.request('document.xml',rcept_no=receipt)
                    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                        candidates=[i for i in archive.infolist() if i.filename.lower().endswith('.xml')]
                        if not candidates:raise ValueError('XML 파일이 없습니다.')
                        # Original zip retained; save all XMLs by basename, never extract paths.
                        chosen=next((i for i in candidates if Path(i.filename).stem==receipt),max(candidates,key=lambda i:i.file_size))
                        destination.mkdir(parents=True,exist_ok=True)
                        (destination/'original.zip').write_bytes(raw)
                        for index,info in enumerate(candidates):
                            if info.file_size>100_000_000:raise ValueError('XML 크기 한도 초과')
                            name=(receipt+'.xml') if info==chosen else 'attachment-'+str(index)+'.xml'
                            (destination/name).write_bytes(archive.read(info))
                manifest['documents'].append(dict(company=company['company_name'],year=document['year'],report_type=document['report_type'],rcept_no=receipt,path=str(target.relative_to(DATA_ROOT)),sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
                print(company['company_name']+' '+str(document['year'])+' '+document['report_type']+' 원본 확보',flush=True)
            except Exception as error:
                manifest['errors'].append(dict(rcept_no=receipt,error=str(error)))
                print(receipt+' 원본 다운로드 실패: '+str(error),flush=True)
            save_json(folder/'manifest.json',manifest)
    print('원본 '+str(len(manifest['documents']))+'개, 실패 '+str(len(manifest['errors']))+'개',flush=True)
    return manifest

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--sector');args=parser.parse_args()
    result=download(args.sector)
    if result['errors']:raise SystemExit(1)
