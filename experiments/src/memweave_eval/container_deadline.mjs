// Separate Linux process; main Pi's blocked JS loop cannot delay this deadline.
import fs from 'node:fs';
const [pidText,deadlineText,trace]=process.argv.slice(2),pid=Number(pidText),deadline=Number(deadlineText);
function identity(){try{const s=fs.readFileSync(`/proc/${pid}/stat`,'utf8');return s.slice(s.lastIndexOf(')')+2).split(' ')[19];}catch{return null;}}
const original=identity();
if(!Number.isInteger(pid)||pid<=1||!original||!Number.isFinite(deadline))process.exit(2);
const timer=setInterval(()=>{
  if(identity()!==original){clearInterval(timer);return;}
  if(Date.now()/1000<deadline)return;
  clearInterval(timer);
  try{fs.appendFileSync(trace,JSON.stringify({event:'local_deadline_stop',pid,timestamp:new Date().toISOString()})+'\n');}catch{}
  try{process.kill(pid,'SIGTERM');}catch{}
  setTimeout(()=>{if(identity()===original)try{process.kill(pid,'SIGKILL');}catch{}},2000);
},250);
