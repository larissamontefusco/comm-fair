"""Official fixed-game M7 comparator and allocation ablation pipeline."""
import argparse
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from comfair.game.checkpoint import atomic_json
from comfair.repair import solve_individual_repair, solve_coalition_repair
from comfair.physical.config import canonical_json
from .provenance import ARTIFACTS, load_inputs, protected_hashes, digest
from .results import PolicyResult
from .pricing_baselines import reprice
from .cooperative import shapley, leave_one_out, nucleolus
from .allocations import constrained_allocation
from .metrics import evaluate
from .frontier import frontier, select_demo
from .ablation import build_ablation

CANONICAL=('m7_policy_comparison.json','m7_price_comparison.json','m7_ablation.json','m7_governance.json')


def build_artifacts(inputs):
    p=inputs.problem;n=len(p.u0);tol=p.tolerance;star=inputs.epsilon_star
    marginals,proportional=leave_one_out(p.values,n,tol)
    def metrics(u):return evaluate(u,p.standalone,p.u0,p.values,star,marginals,inputs.metadata,tol)
    specifications=[];prices={};unavailable=[]
    for pid,rule,description in [('P0_protected_marginal','protected','Authoritative M4 protected marginal settlement'),
        ('P1_midpoint','midpoint','Half of grid plus FIT tariff'),('P2_lower_fit','lower','Buyer-favouring FIT price'),
        ('P3_upper_grid','upper','Seller-favouring grid price')]:
        u,details=reprice(inputs.m4,rule,inputs.dt,tol);prices[pid]=details
        specifications.append((pid,'price',description,'Price-rule benchmark; same quantities and fixed/grid charges','M4 fixed-quantity repricing',u,details,False))
    specifications.append(('G0_market','allocation','M4 market allocation (alias of P0)','Economic protected market anchor','M4 canonical',dict(p.u0),{'alias_of':'P0_protected_marginal'},False))
    specifications.append(('G1_equal_benefit','allocation','Equal absolute cooperative benefit','Every member receives v(N)/N','project comparator',{i:p.values[2**n-1]/n for i in p.members},{},False))
    if proportional is not None:
        specifications.append(('G2_contribution_proportional','allocation','Leave-one-out contribution proportional','Shares proportional to v(N)-v(N without i); signed marginals retained','project comparator',proportional,{},False))
    else:unavailable.append({'policy_id':'G2_contribution_proportional','status':'NOT_APPLICABLE','reason':'zero_sum_leave_one_out_marginals'})
    phi=shapley(p.values,n)
    specifications.append(('G3_shapley','allocation','Exact Shapley allocation','Average marginal contribution across all predecessor subsets','standard cooperative game concept',phi,{'subset_enumeration':'all subsets; no sampling'},False))
    started=perf_counter();nu,certificate=nucleolus(p.values,n,tol);nucleolus_seconds=perf_counter()-started
    specifications.append(('G4_nucleolus','allocation','Exact imputation nucleolus','Lexicographically minimize the sorted proper coalition excesses','standard cooperative game concept',nu,certificate,True))
    for kind,description,assumption in [
        ('fair_least_core_maxmin','ComFair project-defined Fair Least-Core max-min comparator','Exact epsilon*, then max minimum absolute benefit, then min L1 to equal benefit'),
        ('closest_core_l1_to_market','Closest least-core/core L1 allocation to M4','Min total L1 to M4 under efficiency, no-harm and exact epsilon*'),
        ('maxmin_benefit','Absolute max-min benefit governance policy','Exact epsilon*, max minimum benefit, then min L1 to M4')]:
        u,details=constrained_allocation(p.values,n,star,p.u0,kind)
        specifications.append((kind,'governance',description,assumption,'explicit M7 project comparator',u,details,True))
    required={int(i):x for i,x in inputs.m6['coalition']['witness']['benefit_aud'].items()}
    specifications.append(('A4_minimum_repair','necessary_repair','Canonical M6 required repair outcome','Only constitutionally necessary market-anchored repair','M6 canonical',required,{},True))
    unavailable.append({'policy_id':'relative_maxmin_all_members','status':'not_applicable_official_benchmark',
        'reason':'nonpositive_standalone_cost','members':[i for i,b in p.standalone.items() if b<=tol],
        'explanation':'No approved all-member denominator; absolute max-min used; no abs(B_i) normalization'})
    policies=[];candidates=[]
    for pid,family,description,assumption,source,u,details,guaranteed in sorted(specifications):
        raw=metrics(u)
        if guaranteed and not raw['constitutionally_admissible']:
            raise ValueError(f'Governance comparator is inadmissible: {pid}')
        anchor=replace(p,u0=u,market_bills=raw['bills_aud'])
        ir=solve_individual_repair(anchor);cr=solve_coalition_repair(anchor,ir,star)
        repaired=metrics(cr.witness.benefit_aud)
        repair={'anchor_policy_id':pid,'individual':ir.to_dict(),'coalition':cr.to_dict(),'repaired':repaired,
            'governance_transfer_from_M4_aud':{i:p.u0[i]-u[i] for i in p.members},
            'necessary_candidate_repair_tau_aud':cr.witness.tau_aud,
            'combined_transfer_from_M4_aud':{i:p.u0[i]-cr.witness.benefit_aud[i] for i in p.members}}
        metadata={'uses_socioeconomic_data_in_objective':False,'uses_information':'fixed exact game / M4 settlement only',
            'no_harm_guaranteed_by_construction':guaranteed or pid=='G1_equal_benefit',
            'least_core_guaranteed_by_construction':guaranteed,'repair_necessary':cr.r_CR_aud>tol,
            'standard_or_project_defined':source}
        result=PolicyResult(pid,family,description,assumption,source,metadata,raw,repair,details).to_dict()
        policies.append(result)
        if raw['constitutionally_admissible']:
            candidates.append({'policy_id':pid,'source_policy_id':pid,'variant':'raw','metrics':raw,'normative_metadata':metadata})
        elif repaired['constitutionally_admissible']:
            candidates.append({'policy_id':pid+'__repaired','source_policy_id':pid,'variant':'ComFair repaired','metrics':repaired,'normative_metadata':metadata})
        else:
            raise ValueError(f'Candidate repair failed constitutional admissibility: {pid}')
        print(f'M7 evaluated {pid}',flush=True)
    candidates.sort(key=lambda r:r['policy_id'])
    share_tol=tol/max(1.,abs(p.values[2**n-1]))
    demo=select_demo(candidates,tol,share_tol)
    if metrics(p.u0)['coalition']['allocation_in_core']:
        closest=next(r for r in policies if r['policy_id']=='closest_core_l1_to_market')
        if closest['raw']['market_L1_distance_aud']>tol:raise ValueError('Closest-core sanity check failed')
    pair_joint=p.values[2**n-1]-p.values[(2**n-1)^3]
    contribution={'leave_one_out_marginals_aud':marginals,'reference':'grand-coalition leave-one-out, not Shapley',
        'members':{i:{'M4_benefit_aud':p.u0[i],'shapley_aud':phi[i],
            'proportional_aud':None if proportional is None else proportional[i],
            'contribution_share':None if abs(sum(marginals.values()))<=tol else marginals[i]/sum(marginals.values()),
            'market_benefit_share':p.u0[i]/p.values[2**n-1]} for i in p.members},
        'members_1_2':{'marginal_1_aud':marginals[1],'marginal_2_aud':marginals[2],
            'joint_marginal_value_aud':pair_joint,'combined_M4_benefit_aud':p.u0[1]+p.u0[2],
            'joint_minus_market_aud':pair_joint-p.u0[1]-p.u0[2],
            'technical_profiles':{i:inputs.metadata[i] for i in (1,2)},
            'interpretation':'Descriptive game comparison; no causal PV/BESS complementarity claim'}}
    member5={'metadata':inputs.metadata[5],'used_as_weight':False,'policies':[]}
    for row in policies:
        a=row['raw'];b=row['repair_to_constitution']['repaired']
        member5['policies'].append({'policy_id':row['policy_id'],'standalone_bill_aud':p.standalone[5],
            'raw_bill_aud':a['bills_aud'][5],'raw_benefit_aud':a['benefits_aud'][5],
            'repaired_bill_aud':b['bills_aud'][5],'repaired_benefit_aud':b['benefits_aud'][5],
            'raw_justice':a['justice'][5],'repaired_justice':b['justice'][5],
            'raw_harmed':a['benefits_aud'][5]<-tol,'raw_admissible':a['constitutionally_admissible'],
            'repaired_admissible':b['constitutionally_admissible']})
    common={'schema_version':1,'milestone':'M7','currency':'AUD','provenance':inputs.provenance}
    comparison=common|{'policies':policies,'unavailable_policies':unavailable,'households':inputs.metadata,
        'contribution':contribution,'epsilon_star_aud':star,'v_N_aud':p.values[2**n-1],'B_i_aud':p.standalone,
        'C_N_aud':inputs.m3['C_N_aud']}
    governance=common|{'constitution':'efficient; hard no-harm; proper deficits <= epsilon* + monetary tolerance',
        'admissible_candidates':candidates,'inadmissible_raw_candidates':[
            {'policy_id':r['policy_id'],'reasons':r['raw']['inadmissibility_reasons']} for r in policies if not r['raw']['constitutionally_admissible']],
        'frontiers':{'market_vs_gini':frontier(candidates,'gini',tol,share_tol),
                     'market_vs_contribution':frontier(candidates,'contribution',tol,share_tol)},
        'frontier_scope':'Discrete candidate-policy views, not the continuous Pareto set; fixed physical cost',
        'demo_default':demo,'statement':'default != universally fairest policy',
        'member_5_case_study':member5,'members_1_2_contribution':contribution['members_1_2']}
    ablation=common|build_ablation(inputs,policies,candidates,demo)
    pricecomparison=common|{'price_rules':prices,'policy_comparisons':[r for r in policies if r['policy_family']=='price']}
    return dict(zip(CANONICAL,(comparison,pricecomparison,ablation,governance))),{'nucleolus_seconds':nucleolus_seconds,'physical_solve_count':0}


def run_governance(output_dir):
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    if any((output_dir/name).exists() for name in CANONICAL):raise ValueError('Use fresh output directory')
    start=perf_counter()
    try:
        before=protected_hashes();inputs=load_inputs();artifacts,runtime=build_artifacts(inputs)
        if before!=protected_hashes():raise ValueError('Upstream files changed during M7')
        for name,data in artifacts.items():atomic_json(output_dir/name,data)
        from .reports import generate_reports
        generate_reports(output_dir)
        from .audit import audit
        runtime['independent_audit']=audit(output_dir,ARTIFACTS)
        if before!=protected_hashes():raise ValueError('Upstream files changed during output validation')
        runtime.update(total_seconds=perf_counter()-start,artifact_hashes={p.name:digest(p) for p in sorted(output_dir.glob('m7*')) if p.is_file()},
            timing_scope='Provenance, all financial LPs, metrics, tables and figures; no physical resolves')
        atomic_json(output_dir/'m7.runtime.json',runtime)
        print(canonical_json({'status':'DONE','demo':artifacts['m7_governance.json']['demo_default'],'runtime':runtime}))
        return artifacts,runtime
    except Exception as exc:
        atomic_json(output_dir/'m7_failure.json',{'status':'BLOCKED','reason':str(exc),'exception_type':type(exc).__name__})
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',type=Path,required=True)
    run_governance(parser.parse_args().output_dir)
