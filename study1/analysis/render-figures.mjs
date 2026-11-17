// Regenerate the reported-aggregate SVGs; independent of the live experiment.
import {readFileSync,writeFileSync} from "node:fs";
const d=JSON.parse(readFileSync(new URL("../results/reported-aggregates.json",import.meta.url),"utf8"));
if(d.run.comparisons*12!==d.run.judge_calls || d.aggregation.some(r=>r.slice(1).reduce((a,b)=>a+b,0)!==360)) throw Error("Inconsistent reported totals");
function render(d){
 const esc=s=>String(s).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");
 const t=(x,y,s,opt="")=>`<text x="${x}" y="${y}" ${opt}>${esc(s)}</text>`;
 const rect=(x,y,w,h,c)=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${c}"/>`;
 const ln=(x1,y1,x2,y2,c="#82909e",w=1)=>`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${c}" stroke-width="${w}"/>`;
 const svg=(h,title,sub,b)=>`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 940 ${h}" role="img"><title>${esc(title)}</title><rect width="940" height="${h}" fill="white"/><g font-family="Arial, sans-serif" font-size="15" fill="#25364a">${t(26,34,title,'font-size="23" font-weight="bold"')}${t(26,59,sub,'font-size="13" fill="#526477"')}${b}${t(26,h-15,"Source: Study 1 reported aggregates; reconstructed, not raw-data replay.",'font-size="12" fill="#526477"')}</g></svg>\n`;
 const colors=["#187e80","#b95337","#c3cbd4"];
 const bars=(rows,y0)=>rows.map((r,i)=>{let y=y0+i*39,n=r[1]+r[2]+r[3],x=340;let b=t(26,y+17,r[0]);for(let j=0;j<3;j++){const w=465*r[j+1]/n;b+=rect(x,y,w,23,colors[j]);x+=w;}return b+t(820,y+17,`${r[1]}/${n}`,'font-weight="bold"');}).join("");
 const legend=colors.map((c,i)=>rect(340+i*150,75,15,15,c)+t(362+i*150,88,["Correct","Wrong","Undecided"][i])).join("");
 let b=legend+bars(d.aggregation,111)+t(26,405,"Majority-6: language groups",'font-weight="bold"')+bars(d.majority_groups,424)+t(26,520,"Majority-6: reported shortcut conditions",'font-weight="bold"')+bars(d.condition_majorities,538);
 let f1=svg(645,"Figure 1. Correct decisions and coverage","H1/H3 held-out comparisons; bar fractions include undecided outcomes.",b);
 b=t(26,99,"A. Stable correct decisions by language (15 anchors × 6 judges)",'font-weight="bold"');
 for(let i=0;i<d.anchors.length;i++){const r=d.anchors[i],y=118+i*35;b+=t(26,y+17,r[0])+rect(220,y,600,22,"#e9edf1")+rect(220,y,600*r[1]/r[2],22,"#187e80")+t(830,y+17,`${(100*r[1]/r[2]).toFixed(1)}%`);}
 b+=t(26,284,"B. Wrong-shortcut items in Hausa, Yoruba and Igbo (90 comparisons)",'font-weight="bold"')+bars(d.panels,304);
 for(let i=0;i<d.panels.length;i++){let r=d.panels[i];b+=t(26,414+i*27,`${r[0]}: stable agreement ${r[4].toFixed(1)}%`);}
 b+=t(26,483,"All 20 three-judge combinations per language require the archived item-level votes.",'font-size="13" fill="#526477"');
 let f2=svg(530,"Figure 2. Proficiency and the sub-panel outcome contrast","Reported Top-3 vs Bottom-3 only; not a full sub-panel scatterplot.",b);
 b=t(26,100,"A. Own-family selection gap (percentage points)",'font-weight="bold"');
 const px=v=>345+(v+21)*12.1;
 for(const tick of [-20,-10,0,10,20]){b+=ln(px(tick),116,px(tick),667,tick===0?"#627387":"#e6eaf0",tick===0?1.5:1)+t(px(tick),689,`${tick}`,'text-anchor="middle" font-size="13"');}
 for(let i=0;i<d.h2.length;i++){const r=d.h2[i],y=137+i*29;b+=t(26,y+5,`${r[0]} · ${r[1]}`);if(i===0)b+=ln(px(d.english_gap_ci[0]),y,px(d.english_gap_ci[1]),y,"#187e80",2);b+=`<circle cx="${px(r[2])}" cy="${y}" r="5" fill="#187e80"/>`+t(865,y+5,r[2].toFixed(2),'text-anchor="end" font-size="13"');}
 b+=t(26,365,"B. Paired topic-bootstrap contrasts (95% intervals)",'font-weight="bold"');
 for(let i=0;i<d.contrasts.length;i++){const r=d.contrasts[i],y=394+i*39;b+=t(26,y+5,r[0])+ln(px(r[2]),y,px(r[3]),y,"#415a80",2)+ln(px(r[2]),y-4,px(r[2]),y+4,"#415a80")+ln(px(r[3]),y-4,px(r[3]),y+4,"#415a80")+`<circle cx="${px(r[1])}" cy="${y}" r="5" fill="#415a80"/>`+t(915,y+5,`${r[1].toFixed(1)} [${r[2].toFixed(1)}, ${r[3].toFixed(1)}]`,'text-anchor="end" font-size="11"');}
 b+=t(26,721,"Panel A: interval available for English only. Decisive-only English gap: 0 pp (20/72 candidates).",'font-size="12" fill="#526477"');
 let f3=svg(761,"Figure 3. Own-family selection gaps","Seven cells and reported paired contrasts; unreported intervals are deliberately omitted.",b);
 return {"figure-1-coverage.svg":f1,"figure-2-proficiency.svg":f2,"figure-3-family-preference.svg":f3};
}
for(const [name,svg] of Object.entries(render(d)))writeFileSync(new URL("../figures/"+name,import.meta.url),svg);
