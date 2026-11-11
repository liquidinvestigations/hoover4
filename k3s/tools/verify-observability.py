#!/usr/bin/env python3
"""Verify metric and log queries through the operator gateway."""
import json,pathlib,time,urllib.parse
import importlib.util
root=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('verify_operator_login',root/'verify-operator-login.py')
login=importlib.util.module_from_spec(spec);spec.loader.exec_module(login)
browser=login.sign_in()
def get(path):return login.get_json(browser,path)
results={}
for key,query in [('pod_logs','{namespace="kube-system"}'),('events','{job="kubernetes-events"}'),('journal','{job="k3s-journal"}')]:
 params=urllib.parse.urlencode({'query':query,'limit':20,'start':str((time.time_ns()-1800*10**9)),'end':str(time.time_ns())})
 value=get('/grafana/api/datasources/proxy/uid/loki/loki/api/v1/query_range?'+params)
 count=sum(len(x.get('values',[])) for x in value['data']['result']);results[key]={'status':value['status'],'entries':count};assert count>0,(key,value)
targets=get('/prometheus/api/v1/targets')['data']['activeTargets']
results['targets']=[{'job':t['labels'].get('job'),'health':t['health'],'error':t['lastError']} for t in targets]
results['metric_query']=get('/prometheus/api/v1/query?'+urllib.parse.urlencode({'query':'sum(container_memory_working_set_bytes{namespace="kube-system",container!=""})'}))
results['dashboards']=len(get('/grafana/api/search?type=dash-db'))
print(json.dumps(results,indent=2))
