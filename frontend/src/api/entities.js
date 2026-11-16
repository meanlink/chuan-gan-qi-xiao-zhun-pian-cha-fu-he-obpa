import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const monitor={
 settings:()=>api('/monitor/settings'),
 setThreshold:threshold=>api('/monitor/settings/threshold',{method:'PUT',body:JSON.stringify({threshold})}),
 advanceCutoff:cutoff_date=>api('/monitor/settings/cutoff',{method:'PUT',body:JSON.stringify({cutoff_date})}),
 settle:reason=>api('/monitor/settle',{method:'POST',body:JSON.stringify({reason:reason||'manual'})}),
 daily:probe=>api('/monitor/daily'+(probe?'?probe='+encodeURIComponent(probe):'')),
 warnings:probe=>api('/monitor/warnings'+(probe?'?probe='+encodeURIComponent(probe):'')),
 warning:id=>api('/monitor/warnings/'+id),
 notices:()=>api('/monitor/notices'),
};
