"""Control the already running local client without writing credentials to disk."""
import argparse
import json
import urllib.request
from cli_config import add_client_port

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['stop','shutdown','status'])
    add_client_port(parser)
    args=parser.parse_args()
    root=f'http://127.0.0.1:{args.port}'
    with urllib.request.urlopen(root+'/bootstrap',timeout=3) as response:
        token=json.load(response)['token']
    path={'stop':'/engine/stop','shutdown':'/shutdown','status':'/status'}[args.action]
    req=urllib.request.Request(root+'/api/v1'+path,data=b'{}' if args.action!='status' else None,
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=10) as response:
        data=json.load(response)
    if args.action=='status':
        print('state='+data['state'])
    else:
        print('Stop request accepted.')

if __name__=='__main__':main()
