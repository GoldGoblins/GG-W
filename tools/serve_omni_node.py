"""Serve the static public lab panel on loopback only. No keys or RPC proxy."""
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import argparse
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.omni_web import Server,Handler


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8874);args=parser.parse_args()
    if not 1024<=args.port<=65535: parser.error('Port must be 1024..65535')
    directory=Path(__file__).resolve().parents[1]/'knowledge/gg-node-web'
    server=Server(('127.0.0.1',args.port),partial(Handler,directory=str(directory)))
    print('GG public node lab: http://127.0.0.1:'+str(args.port),flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__=='__main__': main()
