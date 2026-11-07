"""Print allowlisted startup facts only; never forward container logs or environment."""
import json
import re
import subprocess
import sys

def summarize(state,logs):
    checks=state.get('Health',{}).get('Log',[])
    categories={
        'heapExhausted':r'heap out of memory|Reached heap limit',
        'dnsFailure':r'ENOTFOUND|EAI_AGAIN',
        'connectionRefused':r'ECONNREFUSED|Connection refused',
        'networkTimeout':r'ETIMEDOUT|fetch failed|ConnectTimeout',
        'databaseFailure':r'SQLITE_ERROR|SQLITE_CANTOPEN|SQLITE_BUSY',
        'configurationFailure':r'ZodError|Invalid configuration|validation failed',
        'addressInUse':r'EADDRINUSE',
        'rateLimited':r'Rate Limit Exceeded|rate limit exceeded',
    }
    return {'status':state.get('Status'),'exitCode':state.get('ExitCode'),
            'oomKilled':state.get('OOMKilled'),
            'health':state.get('Health',{}).get('Status'),
            'checks':[{'exitCode':c.get('ExitCode'),
                       'httpStatus':next((int(n) for n in re.findall(r'status code:\s*(\d{3})',c.get('Output',''))),None),
                       'timedOut':bool(re.search(r'timeout|exceeded',c.get('Output',''),re.I)),
                       'connectionRefused':'ECONNREFUSED' in c.get('Output','')}
                      for c in checks],
            'logSignals':{name:bool(re.search(pattern,logs,re.I)) for name,pattern in categories.items()}}

if __name__=='__main__':
    # Container identifier is supplied by Compose, never a user-controlled URL.
    cid=sys.argv[1]
    details=json.loads(subprocess.check_output(['docker','inspect',cid],text=True))[0]
    result=subprocess.run(['docker','logs','--tail','200',cid],capture_output=True,text=True)
    summary=summarize(details['State'],result.stdout+'\n'+result.stderr)
    summary['restartCount']=details.get('RestartCount')
    print(json.dumps(summary,indent=2))
