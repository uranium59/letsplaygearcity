#!/usr/bin/env python
"""Parse GearCity TurnEvents.xml - comprehensive timeline analysis."""
import sys, os
import xml.etree.ElementTree as ET
from collections import defaultdict
from dotenv import load_dotenv
if sys.platform == "win32": sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

DEFAULT_XML_PATH = os.getenv(
    "GEARCITY_TURN_EVENTS_XML",
    "D:/SteamLibrary/steamapps/common/GearCity/media/Maps/Base City Map/scripts/TurnEvents.xml",
)

def parse_xml(p):
    if not os.path.isfile(p): print("ERROR: not found:",p); sys.exit(1)
    return ET.parse(p).getroot()

def collect_econ(root):
    keys=["buyrate","gas","interest","stockrate","carprice"]
    amap={"buyrate":"rate","gas":"rate","interest":"global","stockrate":"rate","carprice":"rate"}
    data={}
    for ye in root.findall("year"):
        y=int(ye.get("y")); yd={}
        for te in sorted(ye.findall("turn"),key=lambda t:int(t.get("t","0"))):
            for s in ["GameEvts","WorldEvts","NewsEvts"]:
                sec=te.find(s)
                if sec is not None:
                    for k in keys:
                        if k not in yd:
                            el=sec.find(k)
                            if el is not None:
                                v=el.get(amap[k])
                                if v: yd[k]=float(v)
            for k in keys:
                if k not in yd:
                    el=te.find(k)
                    if el is not None:
                        v=el.get(amap[k])
                        if v: yd[k]=float(v)
        data[y]=yd
    return data

def collect_events(root):
    gov,war,news,other=[],[],[],[]
    skip={"buyrate","gas","interest","stockrate","carprice","vehiclepop",
          "office","pensionGrowth","comment","WorldEvts","NewsEvts",
          "GameEvts","turn","year","Evts"}
    for ye in root.findall("year"):
        y=int(ye.get("y"))
        for te in ye.findall("turn"):
            t=int(te.get("t"))
            for el in te.iter():
                tag=el.tag
                if tag=="govern":
                    e={"year":y,"turn":t};e.update(el.attrib);gov.append(e)
                elif tag=="war":
                    e={"year":y,"turn":t};e.update(el.attrib);war.append(e)
                elif tag=="comment":
                    e={"year":y,"turn":t};e.update(el.attrib);news.append(e)
                elif tag not in skip:
                    e={"year":y,"turn":t,"tag":tag};e.update(el.attrib);other.append(e)
    return gov,war,news,other

MONTHS=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
def t2m(t):
    i=int(t)-1
    return MONTHS[i] if 0<=i<12 else str(t)

def flag(val,key):
    if val is None: return "  "
    if key=="buyrate" and val<0.80: return "!!"
    if key=="buyrate" and val<0.90: return "! "
    if key=="gas" and val>3.0: return "!!"
    if key=="gas" and val>2.0: return "! "
    if key=="interest" and val>1.10: return "!!"
    if key=="interest" and val>1.06: return "! "
    if key=="stockrate" and val<0.80: return "!!"
    if key=="stockrate" and val<0.90: return "! "
    if key=="carprice" and val>2.0: return "!!"
    if key=="carprice" and val>1.6: return "! "
    return "  "

def fmt_val(v):
    if v is None: return "      N/A "
    return f"{v:10.4f}"

def main(xml_path: str | None = None):
    path = xml_path or DEFAULT_XML_PATH
    SEP="="*105
    print(SEP)
    print("GEARCITY TurnEvents.xml -- COMPREHENSIVE TIMELINE ANALYSIS")
    print(SEP)
    print("Source:",path)
    print()
    root=parse_xml(path)
    yels=root.findall("year")
    yn=[int(y.get("y")) for y in yels]
    tt=sum(len(y.findall("turn")) for y in yels)
    print(f"Years: {min(yn)} to {max(yn)} ({len(yn)} years), {tt} total turns")
    print()
    ec=collect_econ(root)
    govs,wars,nws,others=collect_events(root)

    print(SEP)
    print("PART 1: YEAR-BY-YEAR ECONOMIC SNAPSHOT (Turn 1 / Jan, fallback to later turns)")
    print(SEP)
    print()
    print("!! = critical, ! = warning")
    print("buyrate: !!<0.80 !<0.90 | gas: !!>3.0 !>2.0 | interest: !!>1.10 !>1.06")
    print("stockrate: !!<0.80 !<0.90 | carprice: !!>2.0 !>1.6")
    print()
    hdr="  Year |   Buyrate  |        Gas |   Interest |  StockRate |   CarPrice | Flags"
    print(hdr)
    print("-"*len(hdr))
    KEYS=["buyrate","gas","interest","stockrate","carprice"]
    prev={}
    for y in sorted(ec):
        v=ec[y]
        if not v:
            print(f"{y:>6} |       N/A  |       N/A  |       N/A  |       N/A  |       N/A  |")
            continue
        fl=[]
        for k in KEYS:
            f=flag(v.get(k),k).strip()
            if f: fl.append(f+k)
        for k in KEYS:
            c,p=v.get(k),prev.get(k)
            if c is not None and p is not None and p!=0:
                pct=((c-p)/p)*100
                if abs(pct)>5:
                    d="UP" if pct>0 else "DN"
                    fl.append(k+d+f"{pct:+.1f}%")
        b=fmt_val(v.get("buyrate"))
        g=fmt_val(v.get("gas"))
        i=fmt_val(v.get("interest"))
        s=fmt_val(v.get("stockrate"))
        cp=fmt_val(v.get("carprice"))
        fs=" ".join(fl)
        print(f"{y:>6} | {b} | {g} | {i} | {s} | {cp} | {fs}")
        for k in KEYS:
            if k in v: prev[k]=v[k]
    print()
    # PART 2
    print(SEP)
    print("PART 2: GOVERN / WAR STATUS CHANGES")
    print(SEP)
    print()
    print("Govern: 1=stable, 0=limited, -1=war, -2=total war")
    print()
    if govs:
        gby=defaultdict(list)
        for g in govs: gby[g["year"]].append(g)
        for gy in sorted(gby):
            print(f"--- {gy} ---")
            for g in sorted(gby[gy],key=lambda x:x["turn"]):
                a={k:v for k,v in g.items() if k not in ("year","turn")}
                astr=", ".join(f"{k}={v}" for k,v in sorted(a.items()))
                tn=g["turn"]
                print(f"  T{tn:>2} ({t2m(tn)}): {astr}")
            print()
    else:
        print("  No <govern> elements found.")
        print()
    if wars:
        print("--- War Events ---")
        wby=defaultdict(list)
        for w in wars: wby[w["year"]].append(w)
        for wy in sorted(wby):
            print(f"  --- {wy} ---")
            for w in sorted(wby[wy],key=lambda x:x["turn"]):
                a={k:v for k,v in w.items() if k not in ("year","turn")}
                astr=", ".join(f"{k}={v}" for k,v in sorted(a.items()))
                tn=w["turn"]
                print(f"    T{tn:>2} ({t2m(tn)}): {astr}")
            print()
    else:
        print("  No <war> elements found.")
        print()
    if others:
        tags=defaultdict(int)
        for o in others: tags[o["tag"]]+=1
        print("--- Other Event Types ---")
        for tag,cnt in sorted(tags.items(),key=lambda x:-x[1]):
            print(f"  <{tag}>: {cnt} occurrences")
        print()
        for tag in sorted(tags):
            all_of=[o for o in others if o["tag"]==tag]
            samps=all_of[:5]
            print(f"  <{tag}> samples (up to 5 of {len(all_of)}):")
            for sv in samps:
                a={k:v for k,v in sv.items() if k not in ("year","turn","tag")}
                astr=", ".join(f"{k}={v}" for k,v in sorted(a.items()))
                tn=sv["turn"]
                print(f"    {sv['year']} T{tn:>2} ({t2m(tn)}): {astr}")
            print()
    print()
    # PART 3
    print(SEP)
    print("PART 3: SUMMARY OF MAJOR EVENTS")
    print(SEP)
    print()
    ys=sorted(ec)
    # Downturns
    print("--- Economic Downturns (buyrate < 0.90) ---")
    ind=False;ds=None;dm=None;dts=[]
    for y in ys:
        br=ec[y].get("buyrate")
        if br is not None:
            if br<0.90 and not ind: ind=True;ds=y;dm=br
            elif br<0.90 and ind: dm=min(dm,br)
            elif br>=0.90 and ind: dts.append((ds,y-1,dm));ind=False
    if ind: dts.append((ds,ys[-1],dm))
    if dts:
        for s,e,m in dts:
            sp=f"{s}-{e}" if s!=e else str(s)
            print(f"  [{sp:>12}] Buyrate trough: {m:.4f}")
    else: print("  None detected.")
    print()
    print("--- Gas Price Spikes (gas > 2.0) ---")
    ins=False;ss=None;sm=None;sps=[]
    for y in ys:
        g=ec[y].get("gas")
        if g is not None:
            if g>2.0 and not ins: ins=True;ss=y;sm=g
            elif g>2.0 and ins: sm=max(sm,g)
            elif g<=2.0 and ins: sps.append((ss,y-1,sm));ins=False
    if ins: sps.append((ss,ys[-1],sm))
    if sps:
        for s,e,m in sps:
            sp=f"{s}-{e}" if s!=e else str(s)
            print(f"  [{sp:>12}] Gas peak: {m:.4f}")
    else: print("  None detected.")
    print()
    print("--- Interest Rate Spikes (interest > 1.06) ---")
    ini=False;i2s=None;im=None;isp=[]
    for y in ys:
        r=ec[y].get("interest")
        if r is not None:
            if r>1.06 and not ini: ini=True;i2s=y;im=r
            elif r>1.06 and ini: im=max(im,r)
            elif r<=1.06 and ini: isp.append((i2s,y-1,im));ini=False
    if ini: isp.append((i2s,ys[-1],im))
    if isp:
        for s,e,m in isp:
            sp=f"{s}-{e}" if s!=e else str(s)
            print(f"  [{sp:>12}] Interest peak: {m:.4f}")
    else: print("  None detected.")
    print()
    print("--- Stock Market Downturns (stockrate < 0.90) ---")
    inc=False;c2s=None;cm=None;crs=[]
    for y in ys:
        sr=ec[y].get("stockrate")
        if sr is not None:
            if sr<0.90 and not inc: inc=True;c2s=y;cm=sr
            elif sr<0.90 and inc: cm=min(cm,sr)
            elif sr>=0.90 and inc: crs.append((c2s,y-1,cm));inc=False
    if inc: crs.append((c2s,ys[-1],cm))
    if crs:
        for s,e,m in crs:
            sp=f"{s}-{e}" if s!=e else str(s)
            print(f"  [{sp:>12}] Stock trough: {m:.4f}")
    else: print("  None detected.")
    print()
    print("--- Top 10 YoY Buyrate DROPS ---")
    chg=[]
    for idx in range(1,len(ys)):
        y=ys[idx];yp=ys[idx-1]
        br=ec[y].get("buyrate");brp=ec[yp].get("buyrate")
        if br is not None and brp is not None and brp!=0:
            chg.append((y,brp,br,((br-brp)/brp)*100))
    chg.sort(key=lambda x:x[3])
    for y,p,c,pct in chg[:10]:
        print(f"  {y}: {p:.4f} -> {c:.4f} ({pct:+.2f}%)")
    print()
    print("--- Top 10 YoY Buyrate RECOVERIES ---")
    for y,p,c,pct in chg[-10:][::-1]:
        print(f"  {y}: {p:.4f} -> {c:.4f} ({pct:+.2f}%)")
    print()
    print("--- Gas Price Extremes ---")
    gd=[(y,ec[y]["gas"]) for y in ys if "gas" in ec[y]]
    if gd:
        gs=sorted(gd,key=lambda x:x[1])
        print("  Lowest 5:")
        for y,gv in gs[:5]: print(f"    {y}: {gv:.4f}")
        print("  Highest 5:")
        for y,gv in gs[-5:][::-1]: print(f"    {y}: {gv:.4f}")
    print()
    print("--- Known Historical Events vs Game Data ---")
    known=[
        (1907,1908,"Panic of 1907"),
        (1914,1918,"World War I"),
        (1920,1921,"Post-WWI Recession"),
        (1929,1933,"Great Depression"),
        (1937,1938,"Recession of 1937-38"),
        (1939,1945,"World War II"),
        (1950,1953,"Korean War"),
        (1956,1957,"Suez Crisis"),
        (1967,1967,"Six-Day War"),
        (1973,1975,"1973 Oil Crisis / OPEC"),
        (1979,1982,"1979 Energy Crisis / Volcker"),
        (1990,1991,"Gulf War / Early 90s Recession"),
        (2001,2002,"Dot-com Bust / 9-11"),
        (2007,2009,"Global Financial Crisis"),
        (2020,2021,"COVID-19 Pandemic"),
    ]
    for start,end,name in known:
        brs=[ec[y].get("buyrate") for y in range(start,end+1) if y in ec and "buyrate" in ec[y]]
        gases=[ec[y].get("gas") for y in range(start,end+1) if y in ec and "gas" in ec[y]]
        if brs:
            mb=min(brs)
            if mb<0.80: lb="DEPRESSION"
            elif mb<0.90: lb="RECESSION"
            elif mb<0.95: lb="MILD"
            else: lb="STABLE"
            gstr=f", gas peak {max(gases):.2f}" if gases else ""
            print(f"  [{start}-{end}] {name:40s} low={mb:.4f} ({lb}){gstr}")
        elif start<=ys[-1]:
            print(f"  [{start}-{end}] {name:40s} (no data)")
    print()
    if nws:
        print(f"--- News Headlines ({len(nws)} total) ---")
        nby=defaultdict(int)
        for n in nws: nby[n["year"]]+=1
        top=sorted(nby.items(),key=lambda x:-x[1])[:20]
        print("  Years with most news:")
        for y,c in top: print(f"    {y}: {c} headlines")
    print()
    print(SEP)
    print("ANALYSIS COMPLETE")
    print(SEP)

if __name__=="__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else None
    main(p)
