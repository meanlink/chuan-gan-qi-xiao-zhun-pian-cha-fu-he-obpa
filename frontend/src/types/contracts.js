/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
/** @typedef {{threshold:number,cutoff_date:string,dirty:boolean,lock_version:number,consecutive_days:number}} MonitorSettings */
/** @typedef {{id:number,probe:string,status:string,streak_start:string,streak_end:string,streak_days:number,max_abs_mean:number,threshold:number,seq:number,evidence:Array,cutoff_date:string}} MonitorWarning */
/** @typedef {{id:number,warning_id:number,probe:string,kind:string,version:number,title:string,body:string,evidence:Array,cutoff_date:string,created_at:number}} MonitorNotice */
export {};
