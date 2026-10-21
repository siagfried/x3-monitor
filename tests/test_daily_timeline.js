const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../dashboard.html'),'utf8');
const scope={};vm.createContext(scope);
vm.runInContext(source.slice(source.indexOf('function dailyTrackSegments('),source.indexOf('function renderDailyTrack(')),scope);
const data={days:[{date:'day',start:0,end:86400}],now:86400};
const span=(start,end,up,down=0)=>({start,end,up,down});
const active=(start,end,up=100)=>({...span(start,end,up),state:'active'});
const hour=(start,spans)=>({start,end:start+3600,spans,up:spans.reduce((sum,s)=>sum+s.up,0),down:0});
function segments(timeline,hours,now=86400){return JSON.parse(JSON.stringify(scope.dailyTrackSegments({...data,now},{timeline,hourly:Object.fromEntries(hours.map(h=>[h.start,h]))},'day')))}
const edges=ss=>ss.map(s=>[s.start,s.end,s.up]);
// A short session keeps its precise minute range and does not absorb a later session's traffic.
assert.deepEqual(edges(segments([active(600,1200,100),active(1800,2400,900)],[hour(0,[span(600,1200,100),span(1800,2400,900)])])),[[600,1200,100],[1800,2400,900]]);
// A short session crossing an hour remains one interval.
assert.deepEqual(edges(segments([active(3300,3900,120)],[hour(0,[span(3300,3600,20)]),hour(3600,[span(3600,3900,100)])])),[[3300,3900,120]]);
// Continuous multi-hour use splits on hours while preserving actual first/last minutes.
assert.deepEqual(edges(segments([active(600,8100,1500)],[hour(0,[span(600,3600,100)]),hour(3600,[span(3600,7200,900)]),hour(7200,[span(7200,8100,500),span(8400,8500,999)])])),[[600,3600,100],[3600,7200,900],[7200,8100,500]]);
// Group/overview event boundaries are not disconnects if activity is continuous.
assert.deepEqual(edges(segments([active(600,1800,40),active(1800,3600,60),active(3600,8100,1400)],[hour(0,[span(600,3600,100)]),hour(3600,[span(3600,7200,900)]),hour(7200,[span(7200,8100,500)])])),[[600,3600,100],[3600,7200,900],[7200,8100,500]]);
// Several disconnected short sessions must not become a continuous hourly run.
assert.deepEqual(segments([active(600,2400),active(3000,4800)],[hour(0,[span(600,2400,100),span(3000,3600,30)]),hour(3600,[span(3600,4800,70)])]).map(s=>[s.start,s.end]),[[600,2400],[3000,4800]]);
assert.deepEqual(edges(segments([active(600,8100,1500)],[hour(0,[span(600,3600,100)]),hour(3600,[span(3600,7200,900)]),hour(7200,[span(7200,8100,500)])],7500)),[[600,3600,100],[3600,7200,900],[7200,7500,500/3]]);
scope.today=()=> 'day';
vm.runInContext(source.slice(source.indexOf('function groupDayData('),source.indexOf('function groupPeriodData(')),scope);
const groupData={...data,clients:[
 {id:'a',timeline:[active(600,1200,100)],hourly:{0:hour(0,[span(600,1200,100)])}},
 {id:'b',timeline:[active(1800,2400,900)],hourly:{0:hour(0,[span(1800,2400,900)])}}
]};
const group=scope.groupDayData(['a','b'],groupData);
assert.deepEqual(JSON.parse(JSON.stringify(scope.dailyTrackSegments(groupData,group,'day'))).map(s=>[s.start,s.end,s.up]),[[600,1200,100],[1800,2400,900]]);
console.log('PASS: short/reconnected/cross-hour/continuous/group/current-time tooltip intervals and traffic');

vm.runInContext(source.slice(source.indexOf('function calendarUsageLevel('),source.indexOf('function renderCards(')),scope);
const GB=1024**3;
assert.equal(scope.calendarUsageLevel({},false,60),'');
assert.equal(scope.calendarUsageLevel({active_seconds:0,up:0,down:0},true,60),'');
assert.equal(scope.calendarUsageLevel({active_seconds:14400,up:2*GB},false,60),' light');
assert.equal(scope.calendarUsageLevel({active_seconds:14401,up:GB},false,60),' light');
assert.equal(scope.calendarUsageLevel({active_seconds:14401,up:GB,down:1},false,60),' heavy');
assert.equal(scope.calendarUsageLevel({active_seconds:1,up:2*GB},true,60),' light');
assert.equal(scope.calendarUsageLevel({active_seconds:0,up:2*GB,down:1},true,60),' heavy');
assert.equal(scope.calendarUsageLevel({active_seconds:1},false,60),' light');
const client={timeline:[active(600,1200,100),active(1800,2400,900)]};
const mean=scope.dailyUsageMean({...data,now:86400},client,'day');
assert.equal(mean,1000/1200);
assert.equal(scope.dailyPieceHeavy(active(600,1200,100),mean),false);
assert.equal(scope.dailyPieceHeavy(active(1800,2400,900),mean),true);
assert.equal(scope.dailyPieceHeavy(active(0,600,100),100/600),false);
// A partial hour is compared by rate, not by its smaller absolute byte count.
assert.equal(scope.dailyPieceHeavy(active(0,60,100),mean),true);
assert.equal(scope.dailyUsageMean(data,{timeline:[active(0,120,120),active(60,180,120)]},'day'),240/180);
assert.equal(scope.dailyUsageMean(data,{timeline:[]},'day'),0);
new vm.Script(source.match(/<script>([\s\S]*?)<\/script>/)[1]);
console.log('PASS: calendar strict thresholds, upload+download, daily interval color comparisons and dashboard syntax');

assert.equal(scope.calendarUsageLevel({active_seconds:1,up:3*GB},false,60),' light');
assert.equal(scope.calendarUsageLevel({active_seconds:1,up:3*GB,down:1},false,60),' extreme');
assert.equal(scope.calendarUsageLevel({active_seconds:1,up:3*GB},true,60),' heavy');
assert.equal(scope.calendarUsageLevel({active_seconds:1,up:3*GB,down:1},true,60),' extreme');
console.log('PASS: orange calendar threshold is strictly above 1/20, independent of duration');
