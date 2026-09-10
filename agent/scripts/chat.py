#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, urllib.request, uuid

def main():
    p=argparse.ArgumentParser(); p.add_argument("message"); p.add_argument("--user",default="cli"); p.add_argument("--thread",default=f"cli-{uuid.uuid4().hex[:8]}"); p.add_argument("--url",default="http://127.0.0.1:8010")
    a=p.parse_args(); data=json.dumps({"message":a.message,"user_id":a.user,"thread_id":a.thread}).encode()
    req=urllib.request.Request(a.url+"/api/chat/stream",data=data,method="POST",headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req) as r:
        for raw in r:
            line=raw.decode().rstrip()
            if line.startswith("event:"): print("\n["+line[6:].strip()+"]",end=" ")
            elif line.startswith("data:"): print(line[5:].strip())
if __name__=="__main__": main()
