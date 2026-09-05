"""Phase 8: human approval gate for calibration recommendations. No live settings are changed."""
import os
from .calibration_backtest import compare
MIN_SAMPLE=int(os.getenv("APPROVAL_MIN_SAMPLE","30"))
MIN_CANDIDATE=int(os.getenv("APPROVAL_MIN_CANDIDATE","10"))
MIN_EXPECTANCY_DELTA=float(os.getenv("APPROVAL_MIN_EXPECTANCY_DELTA","0.10"))

def evaluate():
    result=compare()
    if result.get("status")!="REVIEW_READY":
        return {"decision":"INSUFFICIENT_DATA","reason":f"Need at least {MIN_SAMPLE} closed paper trades.","backtest":result}
    b=result["baseline"]; c=result["candidate"]; reasons=[]
    delta=c["expectancy"]-b["expectancy"]
    if result["candidate_trade_count"]<MIN_CANDIDATE: reasons.append(f"candidate sample below {MIN_CANDIDATE}")
    if delta<MIN_EXPECTANCY_DELTA: reasons.append(f"expectancy improvement {delta:.2f}% is below required {MIN_EXPECTANCY_DELTA:.2f}%")
    if not result["candidate_improves_expectancy"]: reasons.append("candidate does not improve expectancy")
    return {"decision":"READY_FOR_HUMAN_REVIEW" if not reasons else "REJECT","reasons":reasons,"expectancy_delta":delta,"backtest":result}

def format_report():
    a=evaluate(); lines=["🛡️ AURELIS CALIBRATION APPROVAL GATE","",f"Decision: {a['decision']}"]
    if a["decision"]=="INSUFFICIENT_DATA": return "\n".join(lines+[a["reason"],"","🔒 Live strategy unchanged."])
    b=a["backtest"]["baseline"]; c=a["backtest"]["candidate"]
    lines += [f"Baseline: n={b['n']} | win={b['win_rate']:.1f}% | expectancy={b['expectancy']:.2f}%",f"Candidate: n={c['n']} | win={c['win_rate']:.1f}% | expectancy={c['expectancy']:.2f}%",f"Expectancy delta: {a['expectancy_delta']:.2f}%"]
    if a["reasons"]: lines += ["","Reasons:"]+[f"• {x}" for x in a["reasons"]]
    return "\n".join(lines+["","🔒 HUMAN APPROVAL REQUIRED. This gate never changes live strategy settings."])

if __name__=="__main__": print(format_report())
