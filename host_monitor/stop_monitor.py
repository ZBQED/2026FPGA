from pathlib import Path
import json,urllib.request
p=Path(__file__).resolve().parent/'runtime/server_actual.json';d=json.loads(p.read_text(encoding='utf-8'));req=urllib.request.Request(d['url']+'/api/shutdown',data=b'',method='POST',headers={'X-Monitor-Token':d['shutdown_token']});urllib.request.urlopen(req,timeout=3).close();print('Monitor shutdown requested; board services untouched.')
