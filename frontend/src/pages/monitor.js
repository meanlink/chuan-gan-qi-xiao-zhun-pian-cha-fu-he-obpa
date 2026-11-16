import {monitor} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {WarningStatus, NoticeKind} from '../constants/enums.js';
import {esc,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';

const isAdmin=()=>session.user.role==='admin';

export async function monitorPage(id){
 const [settings,warnings,notices,daily]=await Promise.all([
   monitor.settings(),monitor.warnings(),monitor.notices(),monitor.daily()]);
 workspace.monitor={settings,warnings,notices,daily};
 const selected=id?await monitor.warning(Number(id)):null;
 return heading('06 / PROBE WATCH','探头持续偏差监测','按探头与测量日持续跟踪日均残差：绝对值超阈且连续三个日历日才发预警，缺日中断连续性；迟到回填按实验室截止日重算，原预警保留并发布更正或撤销。','<button class="button" id="refresh-monitor">刷新监测 ↻</button>')
 +'<section class="panel monitor-settings"><div class="section-title"><h2>监测口径与结算</h2><span>结算版本 v'+esc(settings.lock_version)+(settings.dirty?' · 待重算':' · 已结算')+'</span></div>'
 +'<div class="monitor-config">'
 +'<form id="threshold-form" class="inline-form"><label>日均残差阈值 °C<input name="threshold" type="number" step="0.01" min="0.01" max="10" value="'+esc(settings.threshold)+'" '+(isAdmin()?'':'disabled')+'></label><button type="submit" class="primary" '+(isAdmin()?'':'disabled')+'>更新阈值</button><p class="hint">超阈且连续 '+esc(settings.consecutive_days)+' 个日历日才预警</p></form>'
 +'<form id="cutoff-form" class="inline-form"><label>实验室结算截止日<input name="cutoff_date" type="date" value="'+esc(settings.cutoff_date||'')+'" required '+(isAdmin()?'':'disabled')+'></label><button type="submit" class="primary" '+(isAdmin()?'':'disabled')+'>推进截止日并结算</button><p class="hint">截止日只能向前推进；回填已结算日将重算后续连续状态</p></form>'
 +'<form id="settle-form" class="inline-form"><label>手动重算<input name="reason" value="manual" maxlength="80"></label><button type="submit" class="button" '+(isAdmin()?'':'disabled')+'>立即重算</button><p class="hint">结算幂等，进程中断后重试不会重复通知</p></form>'
 +'</div></section>'
 +'<div class="two-columns"><section class="panel"><div class="section-title"><h2>预警台账</h2><span>'+warnings.filter(w=>w.status==='active').length+' 条生效中 · 共 '+warnings.length+' 条（含已撤销）</span></div>'
 +(warnings.length?table([{key:'probe',label:'探头'},{key:'status',label:'状态'},{key:'streak',label:'连续超阈段'},{key:'days',label:'连续日数'},{key:'max_abs_mean',label:'最大|日均残差| °C'},{key:'threshold',label:'触发阈值 °C'},{key:'seq',label:'结论版本'},{key:'cutoff_date',label:'结算截止日'}],warnings.map(w=>({probe:w.probe,status:WarningStatus[w.status]||w.status,streak:w.streak_start+' 至 '+w.streak_end,days:w.streak_days,max_abs_mean:w.max_abs_mean,threshold:w.threshold,seq:'v'+w.seq,cutoff_date:w.cutoff_date||'—'})),'暂无预警：尚未出现连续三日超阈的探头。'):'<p class="empty">暂无预警：尚未出现连续三日超阈的探头。</p>')
 +'<p class="hint">点击“追查依据”查看逐日残差与完整通知链。</p>'
 +warnings.map(w=>'<p class="warning-row"><span class="status-badge '+esc(w.status)+'">'+esc(WarningStatus[w.status]||w.status)+'</span><strong>'+esc(w.probe)+'</strong><a class="text-link" href="#/monitor/'+w.id+'">追查依据 ↗</a></p>').join('')
 +'</section>'
 +renderDetail(selected)
 +'</div>'
 +'<section class="panel"><div class="section-title"><h2>监测收件箱（按版本依次呈现）</h2><span>'+notices.length+' 条通知 · 旧计算晚到不覆盖新结论</span></div>'
 +(notices.length?'<div class="notice-inbox">'+notices.map(n=>'<article class="notice-card '+esc(n.kind)+'"><header><span class="notice-kind '+esc(n.kind)+'">'+esc(NoticeKind[n.kind]||n.kind)+' v'+esc(n.version)+'</span><strong>'+esc(n.probe)+'</strong><small>'+date(n.created_at)+'</small></header><h3>'+esc(n.title)+'</h3><p>'+esc(n.body)+'</p><small>结算截止日 '+esc(n.cutoff_date||'—')+' · 依据 '+esc(n.evidence?.length||0)+' 个测量日</small></article>').join('')+'</div>':'<p class="empty">尚无通知。预警、更正与撤销会按结论版本顺序出现在这里。</p>')
 +'</section>'
 +'<section class="panel"><div class="section-title"><h2>探头逐日日均残差</h2><span>仅含已结算窗口（截止日 '+esc(settings.cutoff_date||'未设置')+'）· 旧批次缺探头或日期不纳入</span></div>'
 +(daily.length?daily.map(g=>'<div class="daily-block"><h3>'+esc(g.probe)+'</h3>'+table([{key:'measured_on',label:'测量日'},{key:'n',label:'读数条数'},{key:'mean_residual',label:'日均残差 °C'},{key:'abs_mean_residual',label:'|日均残差| °C'},{key:'over',label:'是否超阈'}],g.days.map(d=>({measured_on:d.measured_on,n:d.n,mean_residual:d.mean_residual,abs_mean_residual:d.abs_mean_residual,over:d.over_threshold?'超阈':'正常'})))).join(''):'<p class="empty">暂无监测读数。接入带探头编号与测量日的批次后开始持续监测。</p>')
 +'</section>';
}

function renderDetail(w){
 if(!w)return '<section class="panel method-sheet"><p class="eyebrow">EVIDENCE</p><h3>预警依据追查</h3><p class="empty">从左侧预警台账选择一条预警，查看逐日日均残差、阈值快照与通知版本链。</p></section>';
 return '<section class="panel method-sheet"><p class="eyebrow">EVIDENCE / 预警依据</p><h3>探头 '+esc(w.probe)+' · '+esc(WarningStatus[w.status]||w.status)+' · 结论 v'+esc(w.seq)+'</h3>'
 +'<p>连续超阈段 '+esc(w.streak_start)+' 至 '+esc(w.streak_end)+'（'+esc(w.streak_days)+' 个连续日历日），触发阈值 '+esc(w.threshold)+'°C，结算截止日 '+esc(w.cutoff_date||'—')+'。</p>'
 +table([{key:'measured_on',label:'测量日'},{key:'n',label:'读数条数'},{key:'mean_residual',label:'日均残差 °C'},{key:'abs_mean_residual',label:'|日均残差| °C'},{key:'threshold',label:'阈值 °C'}],w.evidence.map(e=>({measured_on:e.measured_on,n:e.n,mean_residual:e.mean_residual,abs_mean_residual:e.abs_mean_residual,threshold:e.threshold})))
 +'<h3>通知版本链（原预警保留）</h3>'
 +(w.notices?.length?'<ol class="notice-chain">'+w.notices.map(n=>'<li><span class="notice-kind '+esc(n.kind)+'">'+esc(NoticeKind[n.kind]||n.kind)+' v'+esc(n.version)+'</span><p>'+esc(n.body)+'</p><small>'+date(n.created_at)+'</small></li>').join('')+'</ol>':'<p class="empty">该预警暂无可展示通知。</p>')
 +'</section>';
}

export function bindMonitor(refresh){
 document.querySelector('#refresh-monitor').onclick=refresh;
 submit(document.querySelector('#threshold-form'),async f=>{
   await monitor.setThreshold(Number(f.get('threshold')));notify('阈值已更新，后台将按新口径重算');await refresh();});
 submit(document.querySelector('#cutoff-form'),async f=>{
   await monitor.advanceCutoff(f.get('cutoff_date'));notify('截止日已推进并完成结算');await refresh();});
 submit(document.querySelector('#settle-form'),async f=>{
   await monitor.settle(f.get('reason')||'manual');notify('已按当前口径重算连续状态');await refresh();});
}
