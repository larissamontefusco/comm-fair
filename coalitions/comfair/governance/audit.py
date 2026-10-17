"""Independent stdlib-only audit of M7 JSON/CSV. Run this file directly."""
import argparse
import csv
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path


def require(condition,message):
    if not condition:raise ValueError(message)


def read(path):
    def unique(pairs):
        d={}
        for k,v in pairs:
            require(k not in d,'Duplicate JSON key');d[k]=v
        return d
    return json.loads(Path(path).read_text(),object_pairs_hook=unique)


def rank(rows):
    a=[[Fraction(x) for x in row] for row in rows];r=0
    for j in range(len(a[0])):
        pivot=next((k for k in range(r,len(a)) if a[k][j]),None)
        if pivot is None:continue
        a[r],a[pivot]=a[pivot],a[r];div=a[r][j];a[r]=[x/div for x in a[r]]
        for k in range(r+1,len(a)):
            scale=a[k][j];a[k]=[x-scale*y for x,y in zip(a[k],a[r])]
        r+=1
    return r


def audit(directory,upstream):
    directory,upstream=Path(directory),Path(upstream)
    comparison=read(directory/'m7_policy_comparison.json');governance=read(directory/'m7_governance.json')
    prices=read(directory/'m7_price_comparison.json');ablation=read(directory/'m7_ablation.json')
    m3=read(upstream/'m3_baselines.json');m4=read(upstream/'m4_market.json')
    game=read(upstream/'m5_coalitions.json');core=read(upstream/'m5_core.json');m6=read(upstream/'m6_repair.json')
    provenance=comparison['provenance']
    require(all(x['provenance']==provenance for x in (governance,prices,ablation)), 'Consistent artifact provenance')
    tol=provenance['money_tolerance_aud'];ids=[str(i) for i in range(1,10)]
    require(len(game['records'])==512 and [r['mask'] for r in game['records']]==list(range(512)),'512 masks')
    values={r['mask']:r['value_aud'] for r in game['records']};star=core['certificate']['epsilon_star_aud']
    outside=m3['B_i_aud'];market={i:m4['members'][i]['u0_aud'] for i in ids}
    def close(a,b,label,epsilon=tol):
        require(math.isfinite(a) and math.isfinite(b) and abs(a-b)<=epsilon,label)
    backend=upstream.resolve().parents[1]
    for name,h in provenance['upstream_artifact_hashes'].items():
        require(hashlib.sha256((upstream/name).read_bytes()).hexdigest()==h,'Upstream hash '+name)
    for name,h in provenance['protected_file_sha256'].items():
        require(hashlib.sha256((backend/name).read_bytes()).hexdigest()==h,'Protected '+name)
    for package in ('physical','market','game','repair','governance'):
        h=hashlib.sha256()
        for path in sorted((backend/'comfair'/package).glob('*.py')):h.update(path.name.encode()+b'\0'+path.read_bytes())
        require(h.hexdigest()==provenance[package+'_source_sha256'],'Source '+package)
    require(hashlib.sha256((backend/'reader/ComErgy Benchmark Dataset 2026.xlsx').read_bytes()).hexdigest()==provenance['workbook_sha256'],'Workbook')
    marginals={i:values[511]-values[511^(1<<(int(i)-1))] for i in ids};msum=sum(marginals.values())
    for i in ids:close(comparison['contribution']['leave_one_out_marginals_aud'][i],marginals[i],'Marginal')
    joint=values[511]-values[508];pair=governance['members_1_2_contribution']
    close(pair['joint_marginal_value_aud'],joint,'Joint marginal')
    close(pair['joint_minus_market_aud'],joint-market['1']-market['2'],'Pair comparison')
    def deficits(u):return {s:values[s]-sum(u[str(i)] for i in range(1,10) if s & (1<<(i-1))) for s in range(512)}
    def measure(raw,label):
        u=raw['benefits_aud'];bill=raw['bills_aud'];require(set(u)==set(ids),'Member coverage')
        close(sum(u.values()),values[511],label+' efficiency')
        scale=max(1.,max(abs(x) for x in values.values()),sum(abs(x) for x in u.values()))
        guard=40*math.ulp(scale);threshold=tol+guard
        close(raw['arithmetic_roundoff_guard_aud'],guard,'Roundoff guard',1e-20)
        close(raw['classification_tolerance_aud'],threshold,'Classification threshold',1e-20)
        d=deficits(u);blocks=[s for s in range(1,511) if d[s]>threshold]
        harmed=sum(x < -threshold for x in u.values())
        require(raw['harmed_member_count']==harmed,label+' harmed count')
        require(raw['coalition']['proper_blocking_count']==len(blocks),label+' blocking count')
        worst=min(range(1,511),key=lambda s:(-d[s],s))
        saved_worst=raw['coalition']['worst_proper_coalition']
        require(saved_worst['mask'] in d and 0<saved_worst['mask']<511,label+' worst coalition mask')
        # Python 3.12+ sums floats differently from the pinned Python 3.11 runner.
        # Verify the reported maximizer up to arithmetic uncertainty, not a money-sized tie.
        require(d[worst]-d[saved_worst['mask']]<=guard,label+' worst coalition')
        close(saved_worst['deficit_aud'],d[saved_worst['mask']],label+' worst deficit',guard)
        admissible=harmed==0 and d[worst]<=star+threshold
        require(raw['constitutionally_admissible'] is admissible,label+' constitution')
        close(raw['market_L1_distance_aud'],sum(abs(u[i]-market[i]) for i in ids),label+' market L1')
        close(raw['equal_benefit_L1_distance_aud'],sum(abs(u[i]-values[511]/9) for i in ids),label+' equal L1')
        close(raw['contribution_share_L1_distance'],.5*sum(abs(u[i]/values[511]-marginals[i]/msum) for i in ids),label+' contribution')
        if min(u.values())>=0 and sum(u.values())>tol:
            close(raw['inequality']['gini']['value'],sum(abs(a-b) for a in u.values() for b in u.values())/(18*sum(u.values())),label+' Gini',1e-10)
            close(raw['inequality']['jain']['value'],sum(u.values())**2/(9*sum(x*x for x in u.values())),label+' Jain',1e-10)
        else:
            require(raw['inequality']['gini']['value'] is None and raw['inequality']['jain']['value'] is None,label+' undefined inequality')
        for i in ids:
            close(bill[i],outside[i]-u[i],label+' bills')
            rel=raw['relative_bill_saving'][i]
            if outside[i]<=tol:require(rel['value'] is None and rel['reason']=='nonpositive_standalone_cost',label+' relative saving')
            else:close(rel['value'],u[i]/outside[i],label+' relative saving',1e-10)
            income=comparison['households'][i]['annual_income_aud'];j=raw['justice'][i]
            close(j['policy_energy_burden'],bill[i]/income,label+' burden',1e-10)
            close(j['standalone_energy_burden'],outside[i]/income,label+' baseline burden',1e-10)
            close(j['energy_burden_change'],-u[i]/income,label+' burden change',1e-10)
        return d
    policies={p['policy_id']:p for p in comparison['policies']}
    for pid,p in policies.items():
        measure(p['raw'],pid);repair=p['repair_to_constitution'];measure(repair['repaired'],pid+' repaired')
        anchor=p['raw']['benefits_aud'];cr=repair['coalition'];ir=repair['individual']
        close(ir['r_IR_aud'],sum(max(0.,-x) for x in anchor.values()),pid+' rIR analytical')
        for label,w in [('IR',ir['witness']),('epsilonIR',cr['epsilon_IR_witness']),('CR',cr['witness']),('epsilonCR',cr['epsilon_at_r_CR_witness'])]:
            u=w['benefit_aud'];tau=w['tau_aud'];volume=.5*sum(abs(x) for x in tau.values())
            close(sum(tau.values()),0,pid+label+' balance');close(volume,w['repair_volume_aud'],pid+label+' volume')
            require(min(u.values())>=-tol,pid+label+' no harm')
            for i in ids:
                close(u[i],anchor[i]-tau[i],pid+label+' anchor');close(w['bill_aud'][i],outside[i]-u[i],pid+label+' bill')
            if label!='IR':
                d=deficits(u)
                e=max(0.,max(d[s] for s in range(1,511) if s.bit_count()>=2))
                require(e<=w['epsilon_aud']+tol,pid+label+' coalitions')
                if label.startswith('epsilon'):close(e,w['epsilon_aud'],pid+label+' epsilon')
        close(cr['r_CR_aud'],cr['witness']['repair_volume_aud'],pid+' rCR')
        close(cr['CRP_aud'],cr['r_CR_aud']-ir['r_IR_aud'],pid+' CRP')
        close(cr['RSG_aud'],cr['epsilon_IR_aud']-star,pid+' RSG')
        for i in ids:
            close(repair['repaired']['benefits_aud'][i],cr['witness']['benefit_aud'][i],pid+' repaired witness')
            close(repair['necessary_candidate_repair_tau_aud'][i],cr['witness']['tau_aud'][i],pid+' candidate transfer')
            close(repair['governance_transfer_from_M4_aud'][i],market[i]-anchor[i],pid+' governance transfer')
            close(repair['combined_transfer_from_M4_aud'][i],market[i]-cr['witness']['benefit_aud'][i],pid+' combined transfer')
        require(cr['CRP_aud']>=-tol and cr['RSG_aud']>=-tol,pid+' ordering')
        require(p['normative_metadata']['uses_socioeconomic_data_in_objective'] is False,'No demographic weights')
    phi={}
    for i in ids:
        bit=1<<(int(i)-1)
        phi[i]=sum(math.factorial(s.bit_count())*math.factorial(8-s.bit_count())/math.factorial(9)*(values[s|bit]-values[s]) for s in range(512) if not s&bit)
        close(policies['G3_shapley']['raw']['benefits_aud'][i],phi[i],'Independent full-subset Shapley')
        close(policies['G2_contribution_proportional']['raw']['benefits_aud'][i],values[511]*marginals[i]/msum,'Proportional')
        close(policies['G1_equal_benefit']['raw']['benefits_aud'][i],values[511]/9,'Equal benefit')
    close(sum(phi.values()),values[511],'Shapley efficiency')
    nu=policies['G4_nucleolus'];basis=[[1]*9];active=set(range(1,511));previous=math.inf
    for stage in nu['provenance']['stages']:
        level=stage['excess_level_aud'];require(level<=previous+tol,'Lexicographic levels');previous=level
        ds=deficits(nu['raw']['benefits_aud']);require(all(ds[s]<=level+tol for s in active),'Nucleolus stage constraints')
        for row in stage['added_equalities']:
            s=row['mask'];normal=[int(bool(s&(1<<j))) for j in range(9)]
            require(rank(basis+[normal])==len(basis)+1,'Independent nucleolus equality');basis.append(normal)
            close(sum(nu['raw']['benefits_aud'][str(i)] for i in range(1,10) if s&(1<<(i-1))),row['sum_benefit_aud'],'Nucleolus fixed sum')
        require(rank(basis)==stage['rank'],'Nucleolus rank');active.difference_update(stage['removed_fixed_span_masks'])
    require(rank(basis)==9 and nu['provenance']['certified_unique'],'Nucleolus unique certificate')
    for pid,details in prices['price_rules'].items():
        rule=details['rule'];h=m4['hourly'];grid=h['grid_tariff_aud_per_kwh'];fit=h['fit_aud_per_kwh']
        expected=h['protected_price_aud_per_kwh'] if rule=='protected' else fit if rule=='lower' else grid if rule=='upper' else [(a+b)/2 for a,b in zip(grid,fit)]
        require(details['price_aud_per_kwh']==expected,'Price rule')
        for i in ids:
            q=m4['member_hourly'][i];m=m4['members'][i]
            local=sum(p*(b-s) for p,b,s in zip(expected,q['local_buy_kw'],q['local_sell_kw']))
            bill=m['fixed_fee_aud']+m['grid_import_charge_aud']-m['grid_export_revenue_aud']+local
            close(policies[pid]['raw']['bills_aud'][i],bill,'Repriced unchanged M4 quantities')
    candidates=governance['admissible_candidates'];stol=provenance['share_tolerance']
    for c in candidates:
        p=policies[c['source_policy_id']]
        expected=p['raw'] if c['variant']=='raw' else p['repair_to_constitution']['repaired']
        require(c['metrics']==expected,'Candidate source metrics')
    for view in ('market_vs_gini','market_vs_contribution'):
        def y(c):return c['metrics']['inequality']['gini']['value'] if view=='market_vs_gini' else c['metrics']['contribution_share_L1_distance']
        for a in candidates:
            dominators=[];ay=y(a);ax=a['metrics']['market_L1_distance_aud']
            if ay is not None:
                for b in candidates:
                    by=y(b);bx=b['metrics']['market_L1_distance_aud']
                    if b['policy_id']!=a['policy_id'] and by is not None and bx<=ax+tol and by<=ay+stol and (bx<ax-tol or by<ay-stol):dominators.append(b['policy_id'])
            saved=governance['frontiers'][view][a['policy_id']]
            require(saved['dominated_by']==sorted(dominators),'Frontier dominance')
    pool=sorted(candidates,key=lambda x:x['policy_id'])
    require(all(c['metrics']['constitutionally_admissible'] for c in pool),'Demo eligibility')
    for key,fn,t in [('market_L1_distance_aud',min,tol),('minimum_benefit_aud',max,tol),('contribution_share_L1_distance',min,stol)]:
        valid=[c['metrics'][key] for c in pool if c['metrics'][key] is not None]
        if valid:
            best=fn(valid);pool=[c for c in pool if c['metrics'][key] is not None and abs(c['metrics'][key]-best)<=t]
    require(governance['demo_default']['policy_id']==pool[0]['policy_id'],'Demo lexicographic rule')
    require(governance['demo_default']['universally_fairest'] is False,'Demo interpretation')
    require([s['stage'] for s in ablation['stages']]==['A0','A1','A2','A3','A4','A5'],'Ablation stages')
    require(ablation['stages'][3]['witness']==m6['individual']['witness'] and ablation['stages'][4]['witness']==m6['coalition']['witness'],'Canonical M6 ablation')
    if (directory/'m7_member_outcomes.csv').exists():
        rows=list(csv.DictReader((directory/'m7_member_outcomes.csv').open()))
        require(len(rows)==9*len(policies),'Member CSV coverage')
        for row in rows:close(float(row['raw_benefit_aud']),policies[row['policy_id']]['raw']['benefits_aud'][row['member_id']],'CSV values')
    return {'status':'PASS','policy_count':len(policies),'coalition_count':512,
        'nucleolus_rank':9,'admissible_candidates':len(candidates),'demo_policy':pool[0]['policy_id'],
        'audit_scope':'Independent arithmetic/constraint/rank reconstruction; face-LP optimality also supported by solver traces and synthetic tests'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--artifact-dir',type=Path,required=True);parser.add_argument('--upstream-dir',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(audit(args.artifact_dir,args.upstream_dir),indent=2))
